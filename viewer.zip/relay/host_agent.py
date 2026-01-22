"""
Relay Host Agent

Connects to a relay server and streams screen capture through it.
This enables remote desktop connections across the internet.

Usage:
    python relay_host.py --relay ws://your-relay-server.com:8765
"""

import asyncio
import logging
import time
import sys
import os
import json
from typing import Optional
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import websockets
    from websockets.client import connect, WebSocketClientProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

from host.capture import ScreenCapture, FrameRateLimiter
from host.encoder import FrameEncoder
from common.protocol import (
    MessageType,
    FrameMessage,
    InputMessage,
    ConnectAckMessage,
    InputEventType,
    HEADER_SIZE,
    unpack_header,
)
from relay.server import RelayMessageType

logger = logging.getLogger(__name__)


@dataclass
class RelayHostConfig:
    """Configuration for relay host."""
    relay_url: str = "ws://localhost:8765"
    capture_fps: int = 30
    jpeg_quality: int = 70


class RelayHostAgent:
    """
    Host agent that streams screen through a relay server.

    Instead of listening for direct connections, this agent:
    1. Connects to the relay server
    2. Receives a session code to share
    3. Streams frames through the relay to connected clients
    """

    def __init__(self, config: RelayHostConfig):
        if not WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets library required. Install with: pip install websockets")

        self.config = config
        self.capture = ScreenCapture(target_fps=config.capture_fps)
        self.encoder = FrameEncoder(quality=config.jpeg_quality)
        self.rate_limiter = FrameRateLimiter(target_fps=config.capture_fps)

        self._websocket: Optional[WebSocketClientProtocol] = None
        self._session_code: Optional[str] = None
        self._client_connected = False
        self._running = False

        # Stats
        self._frames_sent = 0
        self._bytes_sent = 0
        self._start_time = 0

    async def connect_to_relay(self) -> bool:
        """Connect to the relay server and register as host."""
        logger.info(f"Connecting to relay server: {self.config.relay_url}")

        try:
            self._websocket = await websockets.connect(
                self.config.relay_url,
                max_size=10 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=10
            )

            # Send host registration
            register_msg = bytes([RelayMessageType.HOST_REGISTER]) + json.dumps({
                'screen_width': self.capture.screen_info.width,
                'screen_height': self.capture.screen_info.height,
                'fps': self.config.capture_fps
            }).encode('utf-8')

            await self._websocket.send(register_msg)

            # Wait for registration confirmation
            response = await asyncio.wait_for(self._websocket.recv(), timeout=10.0)

            if isinstance(response, str):
                response = response.encode()

            if len(response) < 1:
                logger.error("Empty response from relay server")
                return False

            msg_type = response[0]
            payload = response[1:]

            if msg_type == RelayMessageType.HOST_REGISTERED:
                data = json.loads(payload.decode('utf-8'))
                self._session_code = data.get('session_code')
                logger.info(f"Registered with relay. Session code: {self._session_code}")
                return True
            elif msg_type == RelayMessageType.ERROR:
                data = json.loads(payload.decode('utf-8'))
                logger.error(f"Relay error: {data.get('error')}")
                return False
            else:
                logger.error(f"Unexpected response type: {msg_type}")
                return False

        except asyncio.TimeoutError:
            logger.error("Connection timeout")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to relay: {e}")
            return False

    async def start(self) -> None:
        """Start streaming through the relay."""
        if not self._websocket or not self._session_code:
            raise RuntimeError("Not connected to relay. Call connect_to_relay() first.")

        self._running = True
        self._start_time = time.time()

        logger.info(f"Screen: {self.capture.screen_info.width}x{self.capture.screen_info.height}")
        logger.info(f"Target FPS: {self.config.capture_fps}, Quality: {self.config.jpeg_quality}")
        logger.info("Waiting for client to connect...")

        # Start tasks
        receive_task = asyncio.create_task(self._receive_loop())
        stream_task = asyncio.create_task(self._stream_loop())

        try:
            await asyncio.gather(receive_task, stream_task)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop streaming."""
        self._running = False

        if self._websocket:
            try:
                await self._websocket.close()
            except:
                pass

        logger.info(f"Stopped. Frames sent: {self._frames_sent}")

    async def _receive_loop(self) -> None:
        """Receive and handle messages from relay (client input, etc.)."""
        try:
            async for message in self._websocket:
                if not self._running:
                    break

                if isinstance(message, str):
                    message = message.encode()

                if len(message) < 1:
                    continue

                # Check for relay control messages
                msg_type = message[0]

                if msg_type == RelayMessageType.CLIENT_CONNECTED:
                    self._client_connected = True
                    logger.info("Client connected! Starting stream...")

                elif msg_type == RelayMessageType.DISCONNECT:
                    payload = message[1:]
                    try:
                        data = json.loads(payload.decode('utf-8'))
                        reason = data.get('message', data.get('reason', 'Unknown'))
                        logger.info(f"Disconnect: {reason}")
                    except:
                        pass
                    self._client_connected = False

                elif msg_type == RelayMessageType.ERROR:
                    payload = message[1:]
                    try:
                        data = json.loads(payload.decode('utf-8'))
                        logger.error(f"Relay error: {data.get('error')}")
                    except:
                        pass

                else:
                    # This might be input from client - parse as protocol message
                    try:
                        if len(message) >= HEADER_SIZE:
                            proto_type, _, payload_length = unpack_header(message)
                            if proto_type == MessageType.INPUT:
                                payload = message[HEADER_SIZE:HEADER_SIZE + payload_length]
                                input_msg = InputMessage.unpack(payload)
                                await self._handle_input(input_msg)
                    except Exception as e:
                        logger.debug(f"Could not parse message as protocol: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info("Relay connection closed")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
        finally:
            self._running = False

    async def _stream_loop(self) -> None:
        """Capture and stream frames."""
        logger.info("Stream loop started")
        fps_start = time.time()
        fps_count = 0

        while self._running:
            try:
                # Wait for frame timing
                await self.rate_limiter.wait_async()

                # Skip if no client connected
                if not self._client_connected:
                    await asyncio.sleep(0.1)
                    continue

                # Capture frame
                frame = self.capture.grab()

                # Encode
                encoded = self.encoder.encode(frame)

                # Create frame message
                frame_msg = FrameMessage(
                    width=encoded.width,
                    height=encoded.height,
                    frame_data=encoded.data,
                    frame_number=frame.frame_number
                )

                # Send through relay
                packed = frame_msg.pack()
                await self._websocket.send(packed)

                self._frames_sent += 1
                self._bytes_sent += len(packed)
                fps_count += 1

                # Log stats periodically
                elapsed = time.time() - fps_start
                if elapsed >= 5.0:
                    fps = fps_count / elapsed
                    bandwidth = (self._bytes_sent / elapsed) / 1024  # KB/s
                    logger.info(f"Streaming: {fps:.1f} FPS, {bandwidth:.1f} KB/s, "
                               f"frame: {encoded.compressed_size/1024:.1f}KB")
                    fps_start = time.time()
                    fps_count = 0
                    self._bytes_sent = 0

            except websockets.exceptions.ConnectionClosed:
                logger.info("Connection closed during streaming")
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stream error: {e}")
                await asyncio.sleep(0.1)

        logger.info("Stream loop ended")

    async def _handle_input(self, msg: InputMessage) -> None:
        """Handle input event from client."""
        # TODO: Implement actual input injection using Quartz/pyautogui
        if msg.event_type == InputEventType.MOUSE_MOVE:
            logger.debug(f"Input: Mouse move ({msg.x}, {msg.y})")
        elif msg.event_type == InputEventType.MOUSE_DOWN:
            logger.debug(f"Input: Mouse down button={msg.button} at ({msg.x}, {msg.y})")
        elif msg.event_type == InputEventType.MOUSE_UP:
            logger.debug(f"Input: Mouse up button={msg.button}")
        elif msg.event_type == InputEventType.KEY_DOWN:
            logger.debug(f"Input: Key down code={msg.key_code}")
        elif msg.event_type == InputEventType.KEY_UP:
            logger.debug(f"Input: Key up code={msg.key_code}")
        elif msg.event_type == InputEventType.MOUSE_SCROLL:
            logger.debug(f"Input: Scroll delta={msg.scroll_delta}")

    @property
    def session_code(self) -> Optional[str]:
        """Get the session code for this host."""
        return self._session_code


async def run_relay_host(relay_url: str, fps: int = 30, quality: int = 70) -> None:
    """Run the relay host agent."""
    config = RelayHostConfig(
        relay_url=relay_url,
        capture_fps=fps,
        jpeg_quality=quality
    )

    agent = RelayHostAgent(config)

    if not await agent.connect_to_relay():
        print("Failed to connect to relay server")
        return

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           Remote Desktop - Host (Relay Mode)                 ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   SESSION CODE:  {agent.session_code:<42}║
║                                                              ║
║   Share this code with the person who wants to view          ║
║   your screen. They will enter it in their viewer.           ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  Screen: {agent.capture.screen_info.width}x{agent.capture.screen_info.height:<47}║
║  FPS: {fps:<56}║
║  Quality: {quality:<52}║
╠══════════════════════════════════════════════════════════════╣
║  Press Ctrl+C to stop sharing                                ║
╚══════════════════════════════════════════════════════════════╝
""")

    try:
        await agent.start()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await agent.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Remote Desktop Host (Relay Mode)")
    parser.add_argument("--relay", default="ws://localhost:8765",
                       help="Relay server URL (e.g., ws://relay.example.com:8765)")
    parser.add_argument("--fps", type=int, default=30, help="Target FPS")
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality (1-100)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    asyncio.run(run_relay_host(args.relay, args.fps, args.quality))
