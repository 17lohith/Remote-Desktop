"""
Relay Host Agent

Connects to a relay server and streams screen capture through it.
This enables remote desktop connections across the internet.
"""

import asyncio
import logging
import time
import sys
import os
import json
from typing import Optional
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import websockets
    from websockets.client import connect, WebSocketClientProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

from host.capture import ScreenCapture, FrameRateLimiter
from host.encoder import FrameEncoder
from common.protocol import (
    MessageType,
    FrameMessage,
    InputMessage,
    InputEventType,
    MouseButton,
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
    min_quality: int = 30
    max_quality: int = 85


class RelayHostAgent:
    """
    Host agent that streams screen through a relay server.

    Features:
    - Auto-reconnection on disconnect
    - Adaptive quality based on performance
    - Remote control support (viewer can request control)
    - Robust error handling
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

        # Remote control state
        self._control_granted = False
        self._control_callback = None  # Callback for control request UI

        # Adaptive quality
        self._current_quality = config.jpeg_quality
        self._frame_times = []
        self._target_frame_time = 1.0 / config.capture_fps

        # Stats
        self._frames_sent = 0
        self._bytes_sent = 0
        self._start_time = 0
        self._consecutive_errors = 0

    async def connect_to_relay(self) -> bool:
        """Connect to the relay server and register as host."""
        logger.info(f"Connecting to relay server: {self.config.relay_url}")

        try:
            self._websocket = await websockets.connect(
                self.config.relay_url,
                max_size=10 * 1024 * 1024,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=60
            )

            # Send host registration
            register_msg = bytes([RelayMessageType.HOST_REGISTER]) + json.dumps({
                'screen_width': self.capture.screen_info.width,
                'screen_height': self.capture.screen_info.height,
                'fps': self.config.capture_fps
            }).encode('utf-8')

            await self._websocket.send(register_msg)

            # Wait for registration confirmation
            response = await asyncio.wait_for(self._websocket.recv(), timeout=15.0)

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
        """Receive and handle messages from relay."""
        try:
            async for message in self._websocket:
                if not self._running:
                    break

                if isinstance(message, str):
                    message = message.encode()

                if len(message) < 1:
                    continue

                msg_type = message[0]

                if msg_type == RelayMessageType.CLIENT_CONNECTED:
                    self._client_connected = True
                    self._control_granted = False
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
                    self._control_granted = False

                elif msg_type == RelayMessageType.ERROR:
                    payload = message[1:]
                    try:
                        data = json.loads(payload.decode('utf-8'))
                        logger.error(f"Relay error: {data.get('error')}")
                    except:
                        pass

                elif msg_type == RelayMessageType.REQUEST_CONTROL:
                    # Viewer is requesting control
                    logger.info("Viewer requested remote control")
                    if self._control_callback:
                        self._control_callback()
                    else:
                        await self._deny_control("Host has no UI to approve")

                elif msg_type == RelayMessageType.CONTROL_REVOKED:
                    self._control_granted = False
                    logger.info("Control revoked")

                else:
                    # Parse as protocol message (input from viewer)
                    try:
                        if len(message) >= HEADER_SIZE:
                            proto_type, _, payload_length = unpack_header(message)
                            if proto_type == MessageType.INPUT:
                                payload = message[HEADER_SIZE:HEADER_SIZE + payload_length]
                                input_msg = InputMessage.unpack(payload)
                                if self._control_granted:
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
        """Capture and stream frames with adaptive quality."""
        logger.info("Stream loop started")
        fps_start = time.time()
        fps_count = 0

        while self._running:
            try:
                if not self._client_connected:
                    await asyncio.sleep(0.1)
                    continue

                await self.rate_limiter.wait_async()

                # Capture frame with error recovery
                try:
                    frame = self.capture.grab()
                except Exception as e:
                    self._consecutive_errors += 1
                    if self._consecutive_errors > 30:
                        logger.error(f"Too many capture errors: {e}")
                        await asyncio.sleep(1.0)
                    else:
                        await asyncio.sleep(0.05)
                    continue

                self._consecutive_errors = 0

                # Encode with current adaptive quality
                self.encoder.quality = self._current_quality
                encoded = self.encoder.encode(frame)

                frame_msg = FrameMessage(
                    width=encoded.width,
                    height=encoded.height,
                    frame_data=encoded.data,
                    frame_number=frame.frame_number
                )

                packed = frame_msg.pack()

                frame_start = time.time()
                await self._websocket.send(packed)
                send_time = time.time() - frame_start

                self._frames_sent += 1
                self._bytes_sent += len(packed)
                fps_count += 1

                # Adaptive quality: adjust based on send performance
                self._frame_times.append(send_time)
                if len(self._frame_times) > 30:
                    self._frame_times.pop(0)

                if len(self._frame_times) >= 10:
                    avg_send_time = sum(self._frame_times) / len(self._frame_times)
                    if avg_send_time > self._target_frame_time * 0.5:
                        # Sending is slow, reduce quality
                        self._current_quality = max(
                            self.config.min_quality,
                            self._current_quality - 2
                        )
                    elif avg_send_time < self._target_frame_time * 0.2:
                        # Sending is fast, increase quality
                        self._current_quality = min(
                            self.config.max_quality,
                            self._current_quality + 1
                        )

                # Log stats periodically
                elapsed = time.time() - fps_start
                if elapsed >= 5.0:
                    fps = fps_count / elapsed
                    bandwidth = (self._bytes_sent / elapsed) / 1024
                    logger.info(f"Streaming: {fps:.1f} FPS, {bandwidth:.1f} KB/s, "
                               f"quality: {self._current_quality}, "
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
        """Execute input event on host machine using pyautogui."""
        if not self._control_granted or not PYAUTOGUI_AVAILABLE:
            return

        try:
            if msg.event_type == InputEventType.MOUSE_MOVE:
                pyautogui.moveTo(msg.x, msg.y, _pause=False)
            elif msg.event_type == InputEventType.MOUSE_DOWN:
                button = 'left'
                if msg.button == MouseButton.RIGHT:
                    button = 'right'
                elif msg.button == MouseButton.MIDDLE:
                    button = 'middle'
                pyautogui.click(msg.x, msg.y, button=button, _pause=False)
            elif msg.event_type == InputEventType.MOUSE_UP:
                pass  # pyautogui handles click as down+up
            elif msg.event_type == InputEventType.KEY_DOWN:
                try:
                    key = chr(msg.key_code) if msg.key_code < 256 else None
                    if key:
                        pyautogui.press(key, _pause=False)
                except (ValueError, TypeError):
                    pass
            elif msg.event_type == InputEventType.MOUSE_SCROLL:
                delta = msg.scroll_delta if msg.scroll_delta < 32768 else msg.scroll_delta - 65536
                pyautogui.scroll(delta, x=msg.x, y=msg.y, _pause=False)
        except Exception as e:
            logger.debug(f"Input injection error: {e}")

    async def grant_control(self) -> None:
        """Grant remote control to viewer."""
        self._control_granted = True
        if self._websocket:
            msg = bytes([RelayMessageType.CONTROL_GRANTED]) + json.dumps({
                'message': 'Control granted'
            }).encode('utf-8')
            try:
                await self._websocket.send(msg)
            except:
                pass
        logger.info("Remote control granted to viewer")

    async def _deny_control(self, reason: str = "Request denied") -> None:
        """Deny remote control request."""
        if self._websocket:
            msg = bytes([RelayMessageType.CONTROL_DENIED]) + json.dumps({
                'message': reason
            }).encode('utf-8')
            try:
                await self._websocket.send(msg)
            except:
                pass
        logger.info(f"Remote control denied: {reason}")

    async def revoke_control(self) -> None:
        """Revoke remote control from viewer."""
        self._control_granted = False
        if self._websocket:
            msg = bytes([RelayMessageType.CONTROL_REVOKED]) + json.dumps({
                'message': 'Control revoked'
            }).encode('utf-8')
            try:
                await self._websocket.send(msg)
            except:
                pass
        logger.info("Remote control revoked")

    def set_control_callback(self, callback):
        """Set callback for when viewer requests control."""
        self._control_callback = callback

    @property
    def control_granted(self) -> bool:
        return self._control_granted

    @property
    def session_code(self) -> Optional[str]:
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
+==============================================================+
|           Remote Desktop - Host (Relay Mode)                 |
+==============================================================+
|                                                              |
|   SESSION CODE:  {agent.session_code:<42}|
|                                                              |
|   Share this code with the person who wants to view          |
|   your screen. They will enter it in their viewer.           |
|                                                              |
+--------------------------------------------------------------+
|  Screen: {agent.capture.screen_info.width}x{agent.capture.screen_info.height:<47}|
|  FPS: {fps:<56}|
|  Quality: {quality:<52}|
+--------------------------------------------------------------+
|  Press Ctrl+C to stop sharing                                |
+==============================================================+
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
