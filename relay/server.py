"""
Relay Server

WebSocket-based relay server that enables Remote Desktop connections
across NAT/firewalls. All traffic flows through this server.

Architecture:
    Host --> [Relay Server] <-- Client
                   |
            Session Code: "ABC123"

How it works:
1. Host connects via WebSocket, registers as host
2. Server assigns a 6-character session code
3. Host shares code with remote user
4. Client connects with session code
5. Server bridges the two WebSocket connections
6. All frames/input flow through the relay
"""

import asyncio
import logging
import time
import secrets
import string
from dataclasses import dataclass, field
from typing import Dict, Optional, Set
from enum import IntEnum
import json
import struct

try:
    import websockets
    from websockets.server import serve, WebSocketServerProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

logger = logging.getLogger(__name__)


class RelayMessageType(IntEnum):
    """Message types for relay protocol."""
    # Registration
    HOST_REGISTER = 0x01      # Host -> Server: Register as host
    HOST_REGISTERED = 0x02    # Server -> Host: Registration confirmed with code
    CLIENT_JOIN = 0x03        # Client -> Server: Join session with code
    CLIENT_JOINED = 0x04      # Server -> Client: Join confirmed
    CLIENT_CONNECTED = 0x05   # Server -> Host: Client has connected

    # Session management
    DISCONNECT = 0x10         # Either -> Server: Disconnect
    ERROR = 0x11              # Server -> Either: Error message
    PING = 0x12               # Either -> Either: Keep alive
    PONG = 0x13               # Either -> Either: Keep alive response

    # Data relay (these are forwarded as-is)
    RELAY_DATA = 0x20         # Bidirectional: Raw data to relay


def generate_session_code(length: int = 6) -> str:
    """Generate a random session code (alphanumeric, uppercase)."""
    # Exclude confusing characters: 0, O, I, 1, L
    alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class RelaySession:
    """Represents an active relay session."""
    session_code: str
    host_ws: WebSocketServerProtocol
    host_connected_at: float = field(default_factory=time.time)
    client_ws: Optional[WebSocketServerProtocol] = None
    client_connected_at: Optional[float] = None

    # Stats
    bytes_relayed_to_client: int = 0
    bytes_relayed_to_host: int = 0
    frames_relayed: int = 0

    @property
    def has_client(self) -> bool:
        return self.client_ws is not None

    @property
    def is_active(self) -> bool:
        return self.host_ws is not None


class RelayServer:
    """
    WebSocket relay server for Remote Desktop.

    Enables connections across the internet by relaying all traffic
    through a central server.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        if not WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets library required. Install with: pip install websockets")

        self.host = host
        self.port = port

        # Active sessions: code -> RelaySession
        self._sessions: Dict[str, RelaySession] = {}

        # WebSocket -> session code mapping for quick lookup
        self._ws_to_session: Dict[WebSocketServerProtocol, str] = {}

        self._running = False
        self._server = None

        # Stats
        self._total_sessions = 0
        self._total_bytes_relayed = 0

    async def start(self) -> None:
        """Start the relay server."""
        self._running = True

        logger.info(f"Starting relay server on ws://{self.host}:{self.port}")

        async with serve(
            self._handle_connection,
            self.host,
            self.port,
            max_size=10 * 1024 * 1024,  # 10MB max message
            ping_interval=20,
            ping_timeout=10
        ) as server:
            self._server = server
            logger.info("Relay server started. Waiting for connections...")
            await asyncio.Future()  # Run forever

    async def stop(self) -> None:
        """Stop the relay server."""
        self._running = False

        # Close all sessions
        for session in list(self._sessions.values()):
            await self._close_session(session.session_code, "Server shutting down")

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        logger.info("Relay server stopped")

    async def _handle_connection(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a new WebSocket connection."""
        remote = websocket.remote_address
        client_ip = remote[0] if remote else "unknown"
        logger.info(f"New connection from {client_ip}")

        try:
            # Wait for registration message
            raw_data = await asyncio.wait_for(websocket.recv(), timeout=30.0)

            if isinstance(raw_data, str):
                raw_data = raw_data.encode()

            # Parse message type
            if len(raw_data) < 1:
                await self._send_error(websocket, "Empty message")
                return

            msg_type = raw_data[0]
            payload = raw_data[1:]

            if msg_type == RelayMessageType.HOST_REGISTER:
                await self._handle_host_register(websocket, payload)
            elif msg_type == RelayMessageType.CLIENT_JOIN:
                await self._handle_client_join(websocket, payload)
            else:
                await self._send_error(websocket, f"Expected HOST_REGISTER or CLIENT_JOIN, got {msg_type}")
                return

        except asyncio.TimeoutError:
            logger.warning(f"Connection timeout from {client_ip}")
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed: {client_ip}")
        except Exception as e:
            logger.error(f"Error handling connection from {client_ip}: {e}")
        finally:
            # Clean up on disconnect
            await self._handle_disconnect(websocket)

    async def _handle_host_register(self, websocket: WebSocketServerProtocol, payload: bytes) -> None:
        """Handle host registration request."""
        # Generate unique session code
        session_code = self._generate_unique_code()

        # Create session
        session = RelaySession(
            session_code=session_code,
            host_ws=websocket
        )
        self._sessions[session_code] = session
        self._ws_to_session[websocket] = session_code
        self._total_sessions += 1

        # Parse optional host info from payload
        host_info = {}
        if payload:
            try:
                host_info = json.loads(payload.decode('utf-8'))
            except:
                pass

        logger.info(f"Host registered: {session_code}")

        # Send confirmation with session code
        response = bytes([RelayMessageType.HOST_REGISTERED]) + json.dumps({
            'session_code': session_code,
            'message': 'Share this code with the remote user'
        }).encode('utf-8')

        await websocket.send(response)

        # Start relaying for this host
        await self._relay_loop_host(session)

    async def _handle_client_join(self, websocket: WebSocketServerProtocol, payload: bytes) -> None:
        """Handle client join request."""
        # Parse session code from payload
        try:
            data = json.loads(payload.decode('utf-8'))
            session_code = data.get('session_code', '').upper().strip()
        except:
            await self._send_error(websocket, "Invalid join request")
            return

        if not session_code:
            await self._send_error(websocket, "Session code required")
            return

        # Find session
        session = self._sessions.get(session_code)
        if not session:
            await self._send_error(websocket, f"Session not found: {session_code}")
            return

        if session.has_client:
            await self._send_error(websocket, "Session already has a client connected")
            return

        # Join session
        session.client_ws = websocket
        session.client_connected_at = time.time()
        self._ws_to_session[websocket] = session_code

        logger.info(f"Client joined session: {session_code}")

        # Notify client
        response = bytes([RelayMessageType.CLIENT_JOINED]) + json.dumps({
            'session_code': session_code,
            'message': 'Connected to host'
        }).encode('utf-8')
        await websocket.send(response)

        # Notify host that client connected
        host_notify = bytes([RelayMessageType.CLIENT_CONNECTED]) + json.dumps({
            'message': 'Client connected'
        }).encode('utf-8')

        try:
            await session.host_ws.send(host_notify)
        except:
            pass

        # Start relaying for this client
        await self._relay_loop_client(session)

    async def _relay_loop_host(self, session: RelaySession) -> None:
        """Relay messages from host to client."""
        try:
            async for message in session.host_ws:
                if not self._running:
                    break

                # Skip if no client connected
                if not session.client_ws:
                    continue

                # Relay to client
                try:
                    await session.client_ws.send(message)
                    if isinstance(message, bytes):
                        session.bytes_relayed_to_client += len(message)
                        session.frames_relayed += 1
                        self._total_bytes_relayed += len(message)
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"Client disconnected during relay: {session.session_code}")
                    session.client_ws = None
                except Exception as e:
                    logger.error(f"Error relaying to client: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Host disconnected: {session.session_code}")
        except Exception as e:
            logger.error(f"Host relay loop error: {e}")

    async def _relay_loop_client(self, session: RelaySession) -> None:
        """Relay messages from client to host."""
        try:
            async for message in session.client_ws:
                if not self._running:
                    break

                if not session.host_ws:
                    break

                # Relay to host
                try:
                    await session.host_ws.send(message)
                    if isinstance(message, bytes):
                        session.bytes_relayed_to_host += len(message)
                        self._total_bytes_relayed += len(message)
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"Host disconnected during relay: {session.session_code}")
                    break
                except Exception as e:
                    logger.error(f"Error relaying to host: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client disconnected: {session.session_code}")
        except Exception as e:
            logger.error(f"Client relay loop error: {e}")
        finally:
            # Client disconnected, but keep session for host
            if session.session_code in self._sessions:
                session.client_ws = None

    async def _handle_disconnect(self, websocket: WebSocketServerProtocol) -> None:
        """Handle WebSocket disconnection."""
        session_code = self._ws_to_session.pop(websocket, None)
        if not session_code:
            return

        session = self._sessions.get(session_code)
        if not session:
            return

        if session.host_ws == websocket:
            # Host disconnected - close entire session
            logger.info(f"Host disconnected, closing session: {session_code}")
            await self._close_session(session_code, "Host disconnected")
        elif session.client_ws == websocket:
            # Client disconnected - keep session open for host
            logger.info(f"Client disconnected from session: {session_code}")
            session.client_ws = None

            # Notify host
            try:
                notify = bytes([RelayMessageType.DISCONNECT]) + json.dumps({
                    'message': 'Client disconnected'
                }).encode('utf-8')
                await session.host_ws.send(notify)
            except:
                pass

    async def _close_session(self, session_code: str, reason: str) -> None:
        """Close a session and notify connected parties."""
        session = self._sessions.pop(session_code, None)
        if not session:
            return

        # Notify and close client
        if session.client_ws:
            try:
                notify = bytes([RelayMessageType.DISCONNECT]) + json.dumps({
                    'reason': reason
                }).encode('utf-8')
                await session.client_ws.send(notify)
                await session.client_ws.close()
            except:
                pass
            self._ws_to_session.pop(session.client_ws, None)

        # Notify and close host
        if session.host_ws:
            try:
                notify = bytes([RelayMessageType.DISCONNECT]) + json.dumps({
                    'reason': reason
                }).encode('utf-8')
                await session.host_ws.send(notify)
                await session.host_ws.close()
            except:
                pass
            self._ws_to_session.pop(session.host_ws, None)

        logger.info(f"Session closed: {session_code} ({reason})")

    async def _send_error(self, websocket: WebSocketServerProtocol, message: str) -> None:
        """Send error message to client."""
        try:
            error = bytes([RelayMessageType.ERROR]) + json.dumps({
                'error': message
            }).encode('utf-8')
            await websocket.send(error)
        except:
            pass

    def _generate_unique_code(self) -> str:
        """Generate a unique session code."""
        for _ in range(100):
            code = generate_session_code()
            if code not in self._sessions:
                return code
        raise RuntimeError("Could not generate unique session code")

    @property
    def stats(self) -> dict:
        """Get server statistics."""
        return {
            'active_sessions': len(self._sessions),
            'total_sessions': self._total_sessions,
            'total_bytes_relayed': self._total_bytes_relayed,
            'sessions': {
                code: {
                    'has_client': s.has_client,
                    'bytes_to_client': s.bytes_relayed_to_client,
                    'bytes_to_host': s.bytes_relayed_to_host,
                    'frames_relayed': s.frames_relayed
                }
                for code, s in self._sessions.items()
            }
        }


async def run_relay_server(host: str = "0.0.0.0", port: int = 8765) -> None:
    """Run the relay server."""
    server = RelayServer(host, port)

    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        await server.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Remote Desktop Relay Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           Remote Desktop - Relay Server                      ║
╠══════════════════════════════════════════════════════════════╣
║  This server enables connections across the internet.        ║
║  Deploy this on a public server (cloud VPS, etc.)            ║
╠══════════════════════════════════════════════════════════════╣
║  Listening on: ws://{args.host}:{args.port:<30}║
╠══════════════════════════════════════════════════════════════╣
║  Press Ctrl+C to stop                                        ║
╚══════════════════════════════════════════════════════════════╝
""")

    asyncio.run(run_relay_server(args.host, args.port))
