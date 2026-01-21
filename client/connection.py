"""
Client Connection Handler

WebSocket client that connects to a host and receives screen frames.
Handles:
- Connecting to host server
- Receiving and decoding frames
- Sending input events (mouse, keyboard)
- Frame buffering for smooth display
"""

import asyncio
import logging
import time
import sys
import os
from typing import Optional, Callable, Any
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import websockets
    from websockets.client import connect, WebSocketClientProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

from client.decoder import FrameDecoder, FrameBuffer, DecodedFrame
from common.protocol import (
    MessageType,
    FrameMessage,
    InputMessage,
    ConnectMessage,
    ConnectAckMessage,
    DisconnectMessage,
    InputEventType,
    MouseButton,
    HEADER_SIZE,
    unpack_header,
    MESSAGE_CLASSES,
)
from common.config import ClientConfig, get_config

logger = logging.getLogger(__name__)


@dataclass
class ConnectionInfo:
    """Information about the remote host."""
    host: str
    port: int
    screen_width: int
    screen_height: int
    connected_at: float


class ClientConnection:
    """
    WebSocket client that receives screen frames from host.
    """

    def __init__(self, config: Optional[ClientConfig] = None):
        if not WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets library required. Install with: pip install websockets")

        self.config = config or get_config().client
        self.decoder = FrameDecoder()
        self.frame_buffer = FrameBuffer(max_size=3)

        self._websocket: Optional[WebSocketClientProtocol] = None
        self._connection_info: Optional[ConnectionInfo] = None
        self._running = False
        self._receive_task: Optional[asyncio.Task] = None

        # Callbacks
        self._on_frame: Optional[Callable[[DecodedFrame], Any]] = None
        self._on_disconnect: Optional[Callable[[], Any]] = None

        # Stats
        self._frames_received = 0
        self._bytes_received = 0
        self._connect_time = 0

    async def connect(self, host: str, port: int, client_name: str = "Client") -> bool:
        """
        Connect to a host server.

        Args:
            host: Host IP or hostname
            port: Host port
            client_name: Name to identify this client

        Returns:
            True if connection successful
        """
        uri = f"ws://{host}:{port}"
        logger.info(f"Connecting to {uri}...")

        try:
            self._websocket = await websockets.connect(
                uri,
                max_size=10 * 1024 * 1024,  # 10MB max message size
                ping_interval=20,
                ping_timeout=10
            )

            # Send connect message
            connect_msg = ConnectMessage(
                session_id="",  # Not used for direct connection
                client_name=client_name
            )
            await self._websocket.send(connect_msg.pack())

            # Wait for acknowledgment
            raw_data = await asyncio.wait_for(self._websocket.recv(), timeout=10.0)

            if isinstance(raw_data, str):
                raw_data = raw_data.encode()

            msg_type, _, payload_length = unpack_header(raw_data)
            payload = raw_data[HEADER_SIZE:HEADER_SIZE + payload_length]

            if msg_type == MessageType.CONNECT_ACK:
                ack = ConnectAckMessage.unpack(payload)

                if ack.success:
                    self._connection_info = ConnectionInfo(
                        host=host,
                        port=port,
                        screen_width=ack.screen_width,
                        screen_height=ack.screen_height,
                        connected_at=time.time()
                    )
                    self._running = True
                    self._connect_time = time.time()

                    logger.info(f"Connected! Screen: {ack.screen_width}x{ack.screen_height}")
                    return True
                else:
                    logger.error("Connection rejected by host")
                    await self._websocket.close()
                    return False
            else:
                logger.error(f"Unexpected response: {msg_type}")
                await self._websocket.close()
                return False

        except asyncio.TimeoutError:
            logger.error("Connection timeout")
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the host."""
        self._running = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._websocket:
            try:
                # Send disconnect message
                disconnect_msg = DisconnectMessage(reason="Client disconnected")
                await self._websocket.send(disconnect_msg.pack())
                await self._websocket.close()
            except Exception:
                pass

        self._websocket = None
        self._connection_info = None
        logger.info("Disconnected from host")

    async def start_receiving(self) -> None:
        """Start receiving frames in a loop."""
        if not self._websocket:
            raise RuntimeError("Not connected")

        self._receive_task = asyncio.create_task(self._receive_loop())
        await self._receive_task

    async def _receive_loop(self) -> None:
        """Main loop for receiving frames."""
        logger.info("Starting frame receive loop")
        fps_start = time.time()
        fps_count = 0

        try:
            async for raw_data in self._websocket:
                if not self._running:
                    break

                if isinstance(raw_data, str):
                    raw_data = raw_data.encode()

                try:
                    msg_type, _, payload_length = unpack_header(raw_data)
                    payload = raw_data[HEADER_SIZE:HEADER_SIZE + payload_length]

                    if msg_type == MessageType.FRAME:
                        frame_msg = FrameMessage.unpack(payload)
                        self._bytes_received += len(raw_data)

                        # Decode frame
                        decoded = self.decoder.decode(
                            frame_msg.frame_data,
                            frame_number=frame_msg.frame_number
                        )

                        # Add to buffer
                        self.frame_buffer.add(decoded)

                        self._frames_received += 1
                        fps_count += 1

                        # Call frame callback if set
                        if self._on_frame:
                            try:
                                result = self._on_frame(decoded)
                                if asyncio.iscoroutine(result):
                                    await result
                            except Exception as e:
                                logger.error(f"Frame callback error: {e}")

                        # Log FPS periodically
                        elapsed = time.time() - fps_start
                        if elapsed >= 5.0:
                            fps = fps_count / elapsed
                            bandwidth = (self._bytes_received / elapsed) / 1024 / 1024 * 8
                            logger.info(f"Receiving: {fps:.1f} FPS, {bandwidth:.1f} Mbps")
                            fps_start = time.time()
                            fps_count = 0
                            self._bytes_received = 0

                    elif msg_type == MessageType.DISCONNECT:
                        disconnect_msg = DisconnectMessage.unpack(payload)
                        logger.info(f"Host disconnected: {disconnect_msg.reason}")
                        break
                    else:
                        logger.debug(f"Ignoring message type: {msg_type}")

                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"Connection closed: {e}")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
        finally:
            self._running = False
            if self._on_disconnect:
                try:
                    result = self._on_disconnect()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"Disconnect callback error: {e}")

    async def send_mouse_move(self, x: int, y: int) -> None:
        """Send mouse move event."""
        if not self._websocket:
            return

        msg = InputMessage(
            event_type=InputEventType.MOUSE_MOVE,
            x=x,
            y=y
        )
        await self._websocket.send(msg.pack())

    async def send_mouse_down(self, x: int, y: int, button: MouseButton = MouseButton.LEFT) -> None:
        """Send mouse button down event."""
        if not self._websocket:
            return

        msg = InputMessage(
            event_type=InputEventType.MOUSE_DOWN,
            x=x,
            y=y,
            button=button
        )
        await self._websocket.send(msg.pack())

    async def send_mouse_up(self, x: int, y: int, button: MouseButton = MouseButton.LEFT) -> None:
        """Send mouse button up event."""
        if not self._websocket:
            return

        msg = InputMessage(
            event_type=InputEventType.MOUSE_UP,
            x=x,
            y=y,
            button=button
        )
        await self._websocket.send(msg.pack())

    async def send_mouse_scroll(self, x: int, y: int, delta: int) -> None:
        """Send mouse scroll event."""
        if not self._websocket:
            return

        msg = InputMessage(
            event_type=InputEventType.MOUSE_SCROLL,
            x=x,
            y=y,
            scroll_delta=delta
        )
        await self._websocket.send(msg.pack())

    async def send_key_down(self, key_code: int, modifiers: int = 0) -> None:
        """Send key down event."""
        if not self._websocket:
            return

        msg = InputMessage(
            event_type=InputEventType.KEY_DOWN,
            key_code=key_code,
            modifiers=modifiers
        )
        await self._websocket.send(msg.pack())

    async def send_key_up(self, key_code: int, modifiers: int = 0) -> None:
        """Send key up event."""
        if not self._websocket:
            return

        msg = InputMessage(
            event_type=InputEventType.KEY_UP,
            key_code=key_code,
            modifiers=modifiers
        )
        await self._websocket.send(msg.pack())

    def on_frame(self, callback: Callable[[DecodedFrame], Any]) -> None:
        """Set callback for when a frame is received."""
        self._on_frame = callback

    def on_disconnect(self, callback: Callable[[], Any]) -> None:
        """Set callback for when disconnected."""
        self._on_disconnect = callback

    def get_latest_frame(self) -> Optional[DecodedFrame]:
        """Get the most recent frame from the buffer."""
        return self.frame_buffer.get_latest()

    @property
    def is_connected(self) -> bool:
        """Check if connected to host."""
        return self._websocket is not None and self._running

    @property
    def connection_info(self) -> Optional[ConnectionInfo]:
        """Get connection information."""
        return self._connection_info

    @property
    def stats(self) -> dict:
        """Get connection statistics."""
        uptime = time.time() - self._connect_time if self._connect_time else 0
        return {
            'connected': self.is_connected,
            'uptime_seconds': uptime,
            'frames_received': self._frames_received,
            'avg_fps': self._frames_received / uptime if uptime > 0 else 0,
            'decoder_stats': self.decoder.stats
        }


async def run_client(host: str, port: int, duration: int = 0) -> None:
    """
    Run the client viewer (CLI mode for testing).

    Args:
        host: Host to connect to
        port: Port to connect to
        duration: How long to run (0 = forever)
    """
    client = ClientConnection()

    frame_count = 0

    def on_frame(frame: DecodedFrame):
        nonlocal frame_count
        frame_count += 1
        if frame_count % 30 == 0:
            print(f"Received frame {frame.frame_number}: {frame.width}x{frame.height}")

    def on_disconnect():
        print("Disconnected from host")

    client.on_frame(on_frame)
    client.on_disconnect(on_disconnect)

    try:
        if await client.connect(host, port, "TestClient"):
            print(f"Connected! Screen: {client.connection_info.screen_width}x{client.connection_info.screen_height}")

            if duration > 0:
                # Run for specified duration
                receive_task = asyncio.create_task(client.start_receiving())
                await asyncio.sleep(duration)
                await client.disconnect()
            else:
                # Run forever
                await client.start_receiving()
        else:
            print("Failed to connect")

    except KeyboardInterrupt:
        print("\nShutdown requested")
    finally:
        await client.disconnect()
        print(f"\nStats: {client.stats}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Remote Desktop Client")
    parser.add_argument("--host", default="localhost", help="Host to connect to")
    parser.add_argument("--port", type=int, default=9001, help="Port to connect to")
    parser.add_argument("--duration", type=int, default=0, help="Duration in seconds (0 = forever)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"""
╔══════════════════════════════════════════════════════════╗
║         Remote Desktop - Client                          ║
╚══════════════════════════════════════════════════════════╝

Connecting to ws://{args.host}:{args.port}...
Press Ctrl+C to stop.
""")

    asyncio.run(run_client(args.host, args.port, args.duration))
