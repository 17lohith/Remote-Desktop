"""
Signaling Server

Lightweight session broker for Remote Desktop connections.
Handles:
- Session registration (host announces availability)
- Session lookup (client finds host)
- Heartbeat management (session expiration)

Does NOT relay video/input data - only connection metadata.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.protocol import (
    MessageType,
    ErrorCode,
    RegisterMessage,
    RegisterAckMessage,
    LookupMessage,
    LookupResponseMessage,
    HeartbeatMessage,
    HeartbeatAckMessage,
    ErrorMessage,
    read_message,
    write_message,
    generate_session_id,
    validate_session_id,
    HEADER_SIZE,
    unpack_header,
    MESSAGE_CLASSES,
)
from common.config import SignalingConfig, get_config

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents a registered host session."""
    session_id: str
    host_ip: str
    host_port: int
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)

    def is_expired(self, timeout: int) -> bool:
        """Check if session has expired due to missed heartbeats."""
        return (time.time() - self.last_heartbeat) > timeout

    def refresh(self) -> None:
        """Update last heartbeat time."""
        self.last_heartbeat = time.time()


class SessionManager:
    """Manages active sessions with thread-safe operations."""

    def __init__(self, config: SignalingConfig):
        self.config = config
        self.sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def register(self, host_ip: str, host_port: int, session_id: Optional[str] = None) -> Tuple[bool, str, ErrorCode]:
        """
        Register a new session.
        Returns (success, session_id, error_code).
        """
        async with self._lock:
            # Check capacity
            if len(self.sessions) >= self.config.max_sessions:
                return False, "", ErrorCode.CONNECTION_REFUSED

            # Generate or validate session ID
            if session_id:
                if not validate_session_id(session_id):
                    return False, "", ErrorCode.INVALID_MESSAGE
                if session_id in self.sessions:
                    # Session ID already taken - generate new one
                    session_id = self._generate_unique_id()
            else:
                session_id = self._generate_unique_id()

            # Create session
            session = Session(
                session_id=session_id,
                host_ip=host_ip,
                host_port=host_port
            )
            self.sessions[session_id] = session
            logger.info(f"Session registered: {session_id} -> {host_ip}:{host_port}")
            return True, session_id, ErrorCode.SUCCESS

    def _generate_unique_id(self) -> str:
        """Generate a unique session ID."""
        for _ in range(100):  # Prevent infinite loop
            sid = generate_session_id()
            if sid not in self.sessions:
                return sid
        raise RuntimeError("Could not generate unique session ID")

    async def lookup(self, session_id: str) -> Tuple[bool, Optional[Session], ErrorCode]:
        """
        Look up a session by ID.
        Returns (success, session, error_code).
        """
        async with self._lock:
            if not validate_session_id(session_id):
                return False, None, ErrorCode.INVALID_MESSAGE

            session = self.sessions.get(session_id)
            if not session:
                return False, None, ErrorCode.SESSION_NOT_FOUND

            if session.is_expired(self.config.session_timeout):
                del self.sessions[session_id]
                logger.info(f"Session expired during lookup: {session_id}")
                return False, None, ErrorCode.SESSION_EXPIRED

            return True, session, ErrorCode.SUCCESS

    async def heartbeat(self, session_id: str) -> Tuple[bool, ErrorCode]:
        """
        Process heartbeat for a session.
        Returns (success, error_code).
        """
        async with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False, ErrorCode.SESSION_NOT_FOUND

            session.refresh()
            logger.debug(f"Heartbeat received: {session_id}")
            return True, ErrorCode.SUCCESS

    async def unregister(self, session_id: str) -> bool:
        """Remove a session."""
        async with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                logger.info(f"Session unregistered: {session_id}")
                return True
            return False

    async def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count of removed sessions."""
        async with self._lock:
            expired = [
                sid for sid, session in self.sessions.items()
                if session.is_expired(self.config.session_timeout)
            ]
            for sid in expired:
                del self.sessions[sid]
                logger.info(f"Session expired: {sid}")
            return len(expired)

    @property
    def active_count(self) -> int:
        """Number of active sessions."""
        return len(self.sessions)


class SignalingServer:
    """Async TCP signaling server."""

    def __init__(self, config: Optional[SignalingConfig] = None):
        self.config = config or get_config().signaling
        self.session_manager = SessionManager(self.config)
        self._server: Optional[asyncio.Server] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the signaling server."""
        self._server = await asyncio.start_server(
            self._handle_client,
            self.config.host,
            self.config.port
        )
        self._running = True

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        addr = self._server.sockets[0].getsockname()
        logger.info(f"Signaling server started on {addr[0]}:{addr[1]}")

        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the signaling server."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Signaling server stopped")

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired sessions."""
        while self._running:
            await asyncio.sleep(self.config.session_timeout // 2)
            removed = await self.session_manager.cleanup_expired()
            if removed:
                logger.info(f"Cleaned up {removed} expired session(s)")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a client connection."""
        addr = writer.get_extra_info('peername')
        client_ip = addr[0] if addr else "unknown"
        logger.debug(f"New connection from {client_ip}")

        try:
            while True:
                # Read header first
                try:
                    header_data = await asyncio.wait_for(
                        reader.readexactly(HEADER_SIZE),
                        timeout=60.0
                    )
                except asyncio.TimeoutError:
                    logger.debug(f"Connection timeout from {client_ip}")
                    break
                except asyncio.IncompleteReadError:
                    logger.debug(f"Client disconnected: {client_ip}")
                    break

                msg_type, timestamp, payload_length = unpack_header(header_data)

                # Read payload
                if payload_length > 0:
                    payload = await reader.readexactly(payload_length)
                else:
                    payload = b''

                # Parse and handle message
                if msg_type not in MESSAGE_CLASSES:
                    logger.warning(f"Unknown message type: {msg_type}")
                    await self._send_error(writer, ErrorCode.PROTOCOL_ERROR, "Unknown message type")
                    continue

                message = MESSAGE_CLASSES[msg_type].unpack(payload)
                await self._handle_message(message, client_ip, writer)

        except Exception as e:
            logger.error(f"Error handling client {client_ip}: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.debug(f"Connection closed: {client_ip}")

    async def _handle_message(self, message, client_ip: str, writer: asyncio.StreamWriter) -> None:
        """Route message to appropriate handler."""
        if isinstance(message, RegisterMessage):
            await self._handle_register(message, client_ip, writer)
        elif isinstance(message, LookupMessage):
            await self._handle_lookup(message, writer)
        elif isinstance(message, HeartbeatMessage):
            await self._handle_heartbeat(message, writer)
        else:
            logger.warning(f"Unexpected message type: {type(message)}")
            await self._send_error(writer, ErrorCode.PROTOCOL_ERROR, "Unexpected message type")

    async def _handle_register(self, msg: RegisterMessage, client_ip: str, writer: asyncio.StreamWriter) -> None:
        """Handle host registration."""
        success, session_id, error_code = await self.session_manager.register(
            host_ip=client_ip,
            host_port=msg.host_port,
            session_id=msg.session_id if msg.session_id else None
        )

        response = RegisterAckMessage(
            success=success,
            session_id=session_id,
            error_code=error_code
        )
        await write_message(writer, response)

        if success:
            logger.info(f"Host registered: {session_id} from {client_ip}:{msg.host_port}")
        else:
            logger.warning(f"Registration failed for {client_ip}: {error_code.name}")

    async def _handle_lookup(self, msg: LookupMessage, writer: asyncio.StreamWriter) -> None:
        """Handle client lookup request."""
        success, session, error_code = await self.session_manager.lookup(msg.session_id)

        if success and session:
            response = LookupResponseMessage(
                success=True,
                session_id=session.session_id,
                host_ip=session.host_ip,
                host_port=session.host_port,
                error_code=ErrorCode.SUCCESS
            )
            logger.info(f"Lookup success: {msg.session_id} -> {session.host_ip}:{session.host_port}")
        else:
            response = LookupResponseMessage(
                success=False,
                session_id=msg.session_id,
                error_code=error_code
            )
            logger.info(f"Lookup failed: {msg.session_id} - {error_code.name}")

        await write_message(writer, response)

    async def _handle_heartbeat(self, msg: HeartbeatMessage, writer: asyncio.StreamWriter) -> None:
        """Handle heartbeat from host."""
        success, error_code = await self.session_manager.heartbeat(msg.session_id)

        response = HeartbeatAckMessage(session_id=msg.session_id)
        await write_message(writer, response)

    async def _send_error(self, writer: asyncio.StreamWriter, code: ErrorCode, message: str) -> None:
        """Send error response."""
        error = ErrorMessage(error_code=code, message=message)
        await write_message(writer, error)


async def run_server(config: Optional[SignalingConfig] = None) -> None:
    """Main entry point for running the signaling server."""
    server = SignalingServer(config)
    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        await server.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    asyncio.run(run_server())
