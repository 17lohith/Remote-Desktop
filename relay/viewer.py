"""
Relay Client Viewer

Connects to a relay server using a session code to view a remote screen.
Supports window resize, minimize/maximize, and remote control requests.
"""

import asyncio
import logging
import time
import sys
import os
import json
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import websockets
    from websockets.client import connect, WebSocketClientProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

import pygame
import numpy as np

from client.decoder import FrameDecoder, DecodedFrame
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


class RelayViewer:
    """
    PyGame-based viewer that connects through a relay server.
    Supports resize, minimize/maximize, and remote control requests.
    """

    def __init__(self, relay_url: str, session_code: str, scale: float = 1.0):
        if not WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets library required")

        self.relay_url = relay_url
        self.session_code = session_code.upper().strip()
        self.scale = scale

        self.decoder = FrameDecoder()
        self._websocket: Optional[WebSocketClientProtocol] = None

        self.screen: Optional[pygame.Surface] = None
        self.running = False

        # Remote screen dimensions
        self.remote_width = 0
        self.remote_height = 0
        self.display_width = 0
        self.display_height = 0

        # Frame stats
        self.frame_count = 0
        self.fps = 0.0
        self._fps_start = 0
        self._fps_count = 0

        # Latest frame for rendering
        self._latest_surface: Optional[pygame.Surface] = None
        self._original_surface: Optional[pygame.Surface] = None

        # Remote control state
        self._has_control = False
        self._control_requested = False

    async def connect(self) -> bool:
        """Connect to relay server with session code."""
        logger.info(f"Connecting to relay: {self.relay_url}")
        logger.info(f"Session code: {self.session_code}")

        try:
            self._websocket = await websockets.connect(
                self.relay_url,
                max_size=10 * 1024 * 1024,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=60
            )

            join_msg = bytes([RelayMessageType.CLIENT_JOIN]) + json.dumps({
                'session_code': self.session_code
            }).encode('utf-8')

            await self._websocket.send(join_msg)

            response = await asyncio.wait_for(self._websocket.recv(), timeout=15.0)

            if isinstance(response, str):
                response = response.encode()

            if len(response) < 1:
                logger.error("Empty response from relay")
                return False

            msg_type = response[0]
            payload = response[1:]

            if msg_type == RelayMessageType.CLIENT_JOINED:
                data = json.loads(payload.decode('utf-8'))
                logger.info(f"Connected to session: {data.get('session_code')}")
                return True
            elif msg_type == RelayMessageType.ERROR:
                data = json.loads(payload.decode('utf-8'))
                logger.error(f"Connection error: {data.get('error')}")
                return False
            else:
                logger.error(f"Unexpected response: {msg_type}")
                return False

        except asyncio.TimeoutError:
            logger.error("Connection timeout")
            return False
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    def init_display(self, width: int, height: int) -> None:
        """Initialize PyGame display with resizable window."""
        pygame.init()

        self.remote_width = width
        self.remote_height = height
        self.display_width = int(width * self.scale)
        self.display_height = int(height * self.scale)

        # RESIZABLE flag allows minimize/maximize/resize
        self.screen = pygame.display.set_mode(
            (self.display_width, self.display_height),
            pygame.RESIZABLE
        )
        self._update_title()

        logger.info(f"Display: {self.display_width}x{self.display_height} (scale: {self.scale})")

    def _update_title(self):
        """Update window title with status info."""
        control_str = " [CONTROL]" if self._has_control else ""
        fps_str = f" | {self.fps:.1f} FPS" if self.fps > 0 else ""
        pygame.display.set_caption(
            f"Remote Desktop - {self.session_code}{control_str}{fps_str}"
        )

    def on_frame(self, frame: DecodedFrame) -> None:
        """Process incoming frame."""
        try:
            if not self.screen:
                self.init_display(frame.width, frame.height)

            # Store original-size surface
            self._original_surface = pygame.surfarray.make_surface(
                frame.data.swapaxes(0, 1)
            )

            # Scale to current display size
            self._latest_surface = pygame.transform.scale(
                self._original_surface,
                (self.display_width, self.display_height)
            )

            self.frame_count += 1
            self._fps_count += 1

            now = time.time()
            if now - self._fps_start >= 1.0:
                self.fps = self._fps_count / (now - self._fps_start)
                self._fps_count = 0
                self._fps_start = now
                self._update_title()

        except Exception as e:
            logger.error(f"Error processing frame: {e}")

    def render(self) -> None:
        """Render latest frame to display."""
        if self._latest_surface and self.screen:
            self.screen.blit(self._latest_surface, (0, 0))
            pygame.display.flip()

    async def request_control(self) -> None:
        """Request remote control from host."""
        if self._websocket and not self._has_control:
            msg = bytes([RelayMessageType.REQUEST_CONTROL]) + json.dumps({
                'message': 'Requesting remote control'
            }).encode('utf-8')
            try:
                await self._websocket.send(msg)
                self._control_requested = True
                logger.info("Control request sent to host")
            except Exception as e:
                logger.error(f"Failed to send control request: {e}")

    async def send_input(self, msg: InputMessage) -> None:
        """Send input event to host (only if control is granted)."""
        if self._websocket and self._has_control:
            try:
                await self._websocket.send(msg.pack())
            except Exception as e:
                logger.error(f"Failed to send input: {e}")

    async def handle_events(self) -> bool:
        """Handle PyGame events. Returns False if should quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.VIDEORESIZE:
                # Window was resized
                self.display_width = event.w
                self.display_height = event.h
                self.screen = pygame.display.set_mode(
                    (self.display_width, self.display_height),
                    pygame.RESIZABLE
                )
                # Re-scale the current frame
                if self._original_surface:
                    self._latest_surface = pygame.transform.scale(
                        self._original_surface,
                        (self.display_width, self.display_height)
                    )
                self.scale = self.display_width / max(self.remote_width, 1)
                logger.info(f"Window resized to {self.display_width}x{self.display_height}")

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                # F8 = request/toggle control
                if event.key == pygame.K_F8:
                    await self.request_control()
                    continue
                if self._has_control:
                    await self.send_input(InputMessage(
                        event_type=InputEventType.KEY_DOWN,
                        key_code=event.key,
                        modifiers=self._get_modifiers()
                    ))

            elif event.type == pygame.KEYUP:
                if self._has_control:
                    await self.send_input(InputMessage(
                        event_type=InputEventType.KEY_UP,
                        key_code=event.key,
                        modifiers=self._get_modifiers()
                    ))

            elif event.type == pygame.MOUSEMOTION:
                if self._has_control:
                    x, y = self._scale_mouse_pos(event.pos)
                    await self.send_input(InputMessage(
                        event_type=InputEventType.MOUSE_MOVE,
                        x=x, y=y
                    ))

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if self._has_control:
                    x, y = self._scale_mouse_pos(event.pos)
                    await self.send_input(InputMessage(
                        event_type=InputEventType.MOUSE_DOWN,
                        x=x, y=y,
                        button=self._map_button(event.button)
                    ))

            elif event.type == pygame.MOUSEBUTTONUP:
                if self._has_control:
                    x, y = self._scale_mouse_pos(event.pos)
                    await self.send_input(InputMessage(
                        event_type=InputEventType.MOUSE_UP,
                        x=x, y=y,
                        button=self._map_button(event.button)
                    ))

            elif event.type == pygame.MOUSEWHEEL:
                if self._has_control:
                    x, y = pygame.mouse.get_pos()
                    x, y = self._scale_mouse_pos((x, y))
                    await self.send_input(InputMessage(
                        event_type=InputEventType.MOUSE_SCROLL,
                        x=x, y=y,
                        scroll_delta=event.y * 3
                    ))

            # Handle window minimize/restore - keep running
            elif event.type == pygame.ACTIVEEVENT:
                pass  # Don't disconnect on focus change

        return True

    def _scale_mouse_pos(self, pos: tuple) -> tuple:
        """Scale mouse position to remote coordinates."""
        if self.display_width == 0 or self.display_height == 0:
            return pos
        x = int(pos[0] * self.remote_width / self.display_width)
        y = int(pos[1] * self.remote_height / self.display_height)
        return x, y

    def _get_modifiers(self) -> int:
        mods = pygame.key.get_mods()
        modifiers = 0
        if mods & pygame.KMOD_SHIFT:
            modifiers |= 0x01
        if mods & pygame.KMOD_CTRL:
            modifiers |= 0x02
        if mods & pygame.KMOD_ALT:
            modifiers |= 0x04
        if mods & pygame.KMOD_META:
            modifiers |= 0x08
        return modifiers

    def _map_button(self, button: int) -> MouseButton:
        if button == 1:
            return MouseButton.LEFT
        elif button == 2:
            return MouseButton.MIDDLE
        elif button == 3:
            return MouseButton.RIGHT
        return MouseButton.LEFT

    async def receive_loop(self) -> None:
        """Receive frames from relay."""
        try:
            async for message in self._websocket:
                if not self.running:
                    break

                if isinstance(message, str):
                    message = message.encode()

                if len(message) < 1:
                    continue

                msg_type = message[0]

                if msg_type == RelayMessageType.DISCONNECT:
                    payload = message[1:]
                    try:
                        data = json.loads(payload.decode('utf-8'))
                        logger.info(f"Disconnected: {data.get('reason', 'Unknown')}")
                    except:
                        logger.info("Disconnected from host")
                    self.running = False
                    break

                elif msg_type == RelayMessageType.ERROR:
                    payload = message[1:]
                    try:
                        data = json.loads(payload.decode('utf-8'))
                        logger.error(f"Error: {data.get('error')}")
                    except:
                        pass
                    continue

                elif msg_type == RelayMessageType.CONTROL_GRANTED:
                    self._has_control = True
                    self._control_requested = False
                    logger.info("Remote control GRANTED by host")
                    self._update_title()
                    continue

                elif msg_type == RelayMessageType.CONTROL_DENIED:
                    self._has_control = False
                    self._control_requested = False
                    logger.info("Remote control DENIED by host")
                    self._update_title()
                    continue

                elif msg_type == RelayMessageType.CONTROL_REVOKED:
                    self._has_control = False
                    self._control_requested = False
                    logger.info("Remote control REVOKED by host")
                    self._update_title()
                    continue

                # Try to parse as protocol frame message
                try:
                    if len(message) >= HEADER_SIZE:
                        proto_type, _, payload_length = unpack_header(message)
                        if proto_type == MessageType.FRAME:
                            payload = message[HEADER_SIZE:HEADER_SIZE + payload_length]
                            frame_msg = FrameMessage.unpack(payload)
                            decoded = self.decoder.decode(
                                frame_msg.frame_data,
                                frame_number=frame_msg.frame_number
                            )
                            self.on_frame(decoded)
                except Exception as e:
                    logger.debug(f"Could not parse frame: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed")
        except Exception as e:
            logger.error(f"Receive error: {e}")
        finally:
            self.running = False

    async def run(self) -> None:
        """Main viewer loop."""
        if not await self.connect():
            print("Failed to connect. Check the session code and try again.")
            return

        self.running = True
        self._fps_start = time.time()

        receive_task = asyncio.create_task(self.receive_loop())

        print("Connected! Waiting for screen data...")
        print("Press ESC to disconnect, F8 to request control.")

        try:
            while self.running:
                if self.screen:
                    if not await self.handle_events():
                        break
                    self.render()

                await asyncio.sleep(0.001)

        except KeyboardInterrupt:
            logger.info("Interrupted")
        finally:
            self.running = False

            if self._websocket:
                try:
                    await self._websocket.close()
                except:
                    pass

            pygame.quit()
            logger.info("Viewer closed")

    @property
    def has_control(self) -> bool:
        return self._has_control


async def run_relay_viewer(relay_url: str, session_code: str, scale: float = 1.0) -> None:
    """Run the relay viewer."""
    viewer = RelayViewer(relay_url, session_code, scale)
    await viewer.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Remote Desktop Viewer (Relay Mode)")
    parser.add_argument("--relay", default="ws://localhost:8765",
                       help="Relay server URL")
    parser.add_argument("--code", required=True,
                       help="Session code from the host")
    parser.add_argument("--scale", type=float, default=1.0,
                       help="Display scale (0.5 = half size)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"""
+==============================================================+
|           Remote Desktop - Viewer                            |
+--------------------------------------------------------------+
|  Relay:  {args.relay:<52}|
|  Code:   {args.code:<52}|
|  Scale:  {args.scale:<52}|
+--------------------------------------------------------------+
|  Controls:                                                   |
|    - ESC to disconnect                                       |
|    - F8 to request remote control                            |
|    - Resize window freely                                    |
+==============================================================+
""")

    asyncio.run(run_relay_viewer(args.relay, args.code, args.scale))
