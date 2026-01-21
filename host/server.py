"""
Host Streaming Server

WebSocket server that captures screen and streams frames to connected clients.
Handles:
- Screen capture at configurable FPS
- JPEG encoding and streaming
- Input events from clients (mouse, keyboard)
- Connection management
"""

import asyncio
import logging
import time
import sys
import os
from typing import Optional, List
from dataclasses import dataclass, field
import uuid

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import websockets
    from websockets.server import serve, WebSocketServerProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

from host.capture import ScreenCapture, FrameRateLimiter
from host.encoder import FrameEncoder, EncodingFormat
from common.protocol import (
    MessageType,
    FrameMessage,
    InputMessage,
    ConnectMessage,
    ConnectAckMessage,
    DisconnectMessage,
    InputEventType,
    parse_message,
    HEADER_SIZE,
    unpack_header,
    MESSAGE_CLASSES,
)
from common.config import HostConfig, get_config

logger = logging.getLogger(__name__)


@dataclass
class ClientConnection:
    """Represents a connected client."""
    websocket: 'WebSocketServerProtocol'
    client_name: str
    connected_at: float
    frames_sent: int = 0
    last_frame_time: float = 0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


class HostStreamingServer:
    """
    WebSocket server that streams screen capture to clients.
    """

    def __init__(self, config: Optional[HostConfig] = None):
        if not WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets library required. Install with: pip install websockets")

        self.config = config or get_config().host
        self.capture = ScreenCapture(target_fps=self.config.capture_fps)
        self.encoder = FrameEncoder(quality=self.config.jpeg_quality)
        self.rate_limiter = FrameRateLimiter(target_fps=self.config.capture_fps)

        self._clients: dict[str, ClientConnection] = {}
        self._running = False
        self._stream_task: Optional[asyncio.Task] = None
        self._server = None

        # Stats
        self._total_frames_sent = 0
        self._start_time = 0

    async def start(self, host: str = "0.0.0.0", port: int = 9001) -> None:
        """Start the streaming server."""
        self._running = True
        self._start_time = time.time()

        logger.info(f"Starting host streaming server on ws://{host}:{port}")
        logger.info(f"Screen: {self.capture.screen_info.width}x{self.capture.screen_info.height}")
        logger.info(f"Target FPS: {self.config.capture_fps}, JPEG Quality: {self.config.jpeg_quality}")

        async with serve(self._handle_client, host, port, max_size=10 * 1024 * 1024) as server:
            self._server = server
            # Start the frame streaming loop
            self._stream_task = asyncio.create_task(self._stream_loop())

            logger.info(f"Host server ready. Waiting for connections...")
            await asyncio.Future()  # Run forever

    async def stop(self) -> None:
        """Stop the streaming server."""
        self._running = False

        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass

        # Close all client connections
        for client in list(self._clients.values()):
            try:
                await client.websocket.close()
            except Exception:
                pass
        self._clients.clear()

        logger.info("Host server stopped")

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a new client connection."""
        client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
        logger.info(f"New connection from {client_ip}")

        client = ClientConnection(
            websocket=websocket,
            client_name="Client",
            connected_at=time.time()
        )

        try:
            # Wait for connect message
            raw_data = await asyncio.wait_for(websocket.recv(), timeout=10.0)

            if isinstance(raw_data, str):
                raw_data = raw_data.encode()

            msg_type, _, payload_length = unpack_header(raw_data)
            payload = raw_data[HEADER_SIZE:HEADER_SIZE + payload_length]

            if msg_type == MessageType.CONNECT:
                connect_msg = ConnectMessage.unpack(payload)
                client.client_name = connect_msg.client_name
                logger.info(f"Client '{client.client_name}' connected from {client_ip}")

                # Send connection acknowledgment
                ack = ConnectAckMessage(
                    success=True,
                    screen_width=self.capture.screen_info.width,
                    screen_height=self.capture.screen_info.height
                )
                await websocket.send(ack.pack())

                # Add to active clients
                self._clients[client.id] = client

                # Handle incoming messages (input events)
                await self._handle_client_messages(client)
            else:
                logger.warning(f"Expected CONNECT message, got {msg_type}")
                await websocket.close()

        except asyncio.TimeoutError:
            logger.warning(f"Connection timeout from {client_ip}")
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client.client_name} disconnected")
        except Exception as e:
            logger.error(f"Error handling client: {e}")
        finally:
            self._clients.pop(client.id, None)
            logger.info(f"Client '{client.client_name}' removed. Active clients: {len(self._clients)}")

    async def _handle_client_messages(self, client: ClientConnection) -> None:
        """Handle incoming messages from a client (mainly input events)."""
        try:
            async for raw_data in client.websocket:
                if isinstance(raw_data, str):
                    raw_data = raw_data.encode()

                try:
                    msg_type, _, payload_length = unpack_header(raw_data)
                    payload = raw_data[HEADER_SIZE:HEADER_SIZE + payload_length]

                    if msg_type == MessageType.INPUT:
                        input_msg = InputMessage.unpack(payload)
                        await self._handle_input(input_msg)
                    elif msg_type == MessageType.DISCONNECT:
                        logger.info(f"Client {client.client_name} requested disconnect")
                        break
                    else:
                        logger.debug(f"Ignoring message type: {msg_type}")

                except Exception as e:
                    logger.error(f"Error parsing client message: {e}")

        except websockets.exceptions.ConnectionClosed:
            pass

    async def _handle_input(self, msg: InputMessage) -> None:
        """Process input event from client."""
        # TODO: Implement actual input injection using Quartz events
        # For now, just log the input
        if msg.event_type == InputEventType.MOUSE_MOVE:
            logger.debug(f"Mouse move: ({msg.x}, {msg.y})")
        elif msg.event_type == InputEventType.MOUSE_DOWN:
            logger.debug(f"Mouse down: button={msg.button} at ({msg.x}, {msg.y})")
        elif msg.event_type == InputEventType.MOUSE_UP:
            logger.debug(f"Mouse up: button={msg.button} at ({msg.x}, {msg.y})")
        elif msg.event_type == InputEventType.KEY_DOWN:
            logger.debug(f"Key down: code={msg.key_code} modifiers={msg.modifiers}")
        elif msg.event_type == InputEventType.KEY_UP:
            logger.debug(f"Key up: code={msg.key_code}")
        elif msg.event_type == InputEventType.MOUSE_SCROLL:
            logger.debug(f"Scroll: delta={msg.scroll_delta}")

    async def _stream_loop(self) -> None:
        """Main loop that captures and streams frames."""
        logger.info("Starting frame streaming loop")
        frame_count = 0
        fps_start_time = time.time()
        fps_frame_count = 0

        while self._running:
            try:
                # Wait for frame timing
                await self.rate_limiter.wait_async()

                # Skip if no clients
                if not self._clients:
                    await asyncio.sleep(0.1)
                    continue

                # Capture frame
                frame = self.capture.grab()

                # Encode frame
                encoded = self.encoder.encode(frame)

                # Create frame message
                frame_msg = FrameMessage(
                    width=encoded.width,
                    height=encoded.height,
                    frame_data=encoded.data,
                    frame_number=frame.frame_number
                )
                packed_frame = frame_msg.pack()

                # Send to all connected clients
                disconnected = []
                for client in list(self._clients.values()):
                    try:
                        await client.websocket.send(packed_frame)
                        client.frames_sent += 1
                        client.last_frame_time = time.time()
                    except websockets.exceptions.ConnectionClosed:
                        disconnected.append(client)
                    except Exception as e:
                        logger.error(f"Error sending to client: {e}")
                        disconnected.append(client)

                # Remove disconnected clients
                for client in disconnected:
                    self._clients.pop(client.id, None)

                self._total_frames_sent += 1
                frame_count += 1
                fps_frame_count += 1

                # Log FPS every 5 seconds
                elapsed = time.time() - fps_start_time
                if elapsed >= 5.0:
                    fps = fps_frame_count / elapsed
                    logger.info(f"Streaming: {fps:.1f} FPS, {len(self._clients)} clients, "
                               f"frame size: {encoded.compressed_size/1024:.1f}KB")
                    fps_start_time = time.time()
                    fps_frame_count = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in stream loop: {e}")
                await asyncio.sleep(0.1)

        logger.info(f"Stream loop ended. Total frames sent: {self._total_frames_sent}")

    @property
    def stats(self) -> dict:
        """Get server statistics."""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            'uptime_seconds': uptime,
            'total_frames_sent': self._total_frames_sent,
            'active_clients': len(self._clients),
            'avg_fps': self._total_frames_sent / uptime if uptime > 0 else 0,
            'encoder_stats': self.encoder.stats
        }


async def run_host_server(host: str = "0.0.0.0", port: int = 9001,
                          fps: int = 30, quality: int = 70) -> None:
    """Run the host streaming server."""
    config = HostConfig(
        capture_fps=fps,
        jpeg_quality=quality,
        listen_port=port
    )

    server = HostStreamingServer(config)

    try:
        await server.start(host, port)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        await server.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Remote Desktop Host Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9001, help="Port to listen on")
    parser.add_argument("--fps", type=int, default=30, help="Target FPS")
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality (1-100)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"""
╔══════════════════════════════════════════════════════════╗
║         Remote Desktop - Host Server                     ║
╚══════════════════════════════════════════════════════════╝

Starting host server...
  - WebSocket: ws://{args.host}:{args.port}
  - FPS: {args.fps}
  - Quality: {args.quality}

Press Ctrl+C to stop.
""")

    asyncio.run(run_host_server(args.host, args.port, args.fps, args.quality))
