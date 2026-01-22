"""
Relay Client Viewer

Connects to a relay server using a session code to view a remote screen.
This enables remote desktop connections across the internet.

Usage:
    python relay_viewer.py --relay ws://relay-server.com:8765 --code ABC123
"""

import asyncio
import logging
import time
import sys
import os
import json
from typing import Optional

# Add project root to path
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

    Uses a session code to connect to a remote host through the relay.
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

        # Remote screen dimensions (will be set from first frame)
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

    async def connect(self) -> bool:
        """Connect to relay server with session code."""
        logger.info(f"Connecting to relay: {self.relay_url}")
        logger.info(f"Session code: {self.session_code}")

        try:
            self._websocket = await websockets.connect(
                self.relay_url,
                max_size=10 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=10
            )

            # Send join request
            join_msg = bytes([RelayMessageType.CLIENT_JOIN]) + json.dumps({
                'session_code': self.session_code
            }).encode('utf-8')

            await self._websocket.send(join_msg)

            # Wait for response
            response = await asyncio.wait_for(self._websocket.recv(), timeout=10.0)

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
        """Initialize PyGame display with given dimensions."""
        pygame.init()

        self.remote_width = width
        self.remote_height = height
        self.display_width = int(width * self.scale)
        self.display_height = int(height * self.scale)

        self.screen = pygame.display.set_mode((self.display_width, self.display_height))
        pygame.display.set_caption(f"Remote Desktop - {self.session_code}")

        logger.info(f"Display: {self.display_width}x{self.display_height} (scale: {self.scale})")

    def on_frame(self, frame: DecodedFrame) -> None:
        """Process incoming frame."""
        try:
            # Initialize display on first frame
            if not self.screen:
                self.init_display(frame.width, frame.height)

            # Convert numpy array to pygame surface
            surface = pygame.surfarray.make_surface(frame.data.swapaxes(0, 1))

            # Scale if needed
            if self.scale != 1.0:
                surface = pygame.transform.scale(surface, (self.display_width, self.display_height))

            self._latest_surface = surface
            self.frame_count += 1
            self._fps_count += 1

            # Update FPS counter
            now = time.time()
            if now - self._fps_start >= 1.0:
                self.fps = self._fps_count / (now - self._fps_start)
                self._fps_count = 0
                self._fps_start = now
                pygame.display.set_caption(
                    f"Remote Desktop - {self.session_code} | {self.fps:.1f} FPS"
                )

        except Exception as e:
            logger.error(f"Error processing frame: {e}")

    def render(self) -> None:
        """Render latest frame to display."""
        if self._latest_surface and self.screen:
            self.screen.blit(self._latest_surface, (0, 0))
            pygame.display.flip()

    async def send_input(self, msg: InputMessage) -> None:
        """Send input event to host."""
        if self._websocket:
            try:
                await self._websocket.send(msg.pack())
            except Exception as e:
                logger.error(f"Failed to send input: {e}")

    async def handle_events(self) -> bool:
        """Handle PyGame events. Returns False if should quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                await self.send_input(InputMessage(
                    event_type=InputEventType.KEY_DOWN,
                    key_code=event.key,
                    modifiers=self._get_modifiers()
                ))

            elif event.type == pygame.KEYUP:
                await self.send_input(InputMessage(
                    event_type=InputEventType.KEY_UP,
                    key_code=event.key,
                    modifiers=self._get_modifiers()
                ))

            elif event.type == pygame.MOUSEMOTION:
                x, y = self._scale_mouse_pos(event.pos)
                await self.send_input(InputMessage(
                    event_type=InputEventType.MOUSE_MOVE,
                    x=x, y=y
                ))

            elif event.type == pygame.MOUSEBUTTONDOWN:
                x, y = self._scale_mouse_pos(event.pos)
                await self.send_input(InputMessage(
                    event_type=InputEventType.MOUSE_DOWN,
                    x=x, y=y,
                    button=self._map_button(event.button)
                ))

            elif event.type == pygame.MOUSEBUTTONUP:
                x, y = self._scale_mouse_pos(event.pos)
                await self.send_input(InputMessage(
                    event_type=InputEventType.MOUSE_UP,
                    x=x, y=y,
                    button=self._map_button(event.button)
                ))

            elif event.type == pygame.MOUSEWHEEL:
                x, y = pygame.mouse.get_pos()
                x, y = self._scale_mouse_pos((x, y))
                await self.send_input(InputMessage(
                    event_type=InputEventType.MOUSE_SCROLL,
                    x=x, y=y,
                    scroll_delta=event.y * 3
                ))

        return True

    def _scale_mouse_pos(self, pos: tuple) -> tuple:
        """Scale mouse position to remote coordinates."""
        x = int(pos[0] / self.scale)
        y = int(pos[1] / self.scale)
        return x, y

    def _get_modifiers(self) -> int:
        """Get keyboard modifiers."""
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
        """Map PyGame button to protocol button."""
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

                # Check for relay control messages
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

                # Try to parse as protocol frame message
                try:
                    if len(message) >= HEADER_SIZE:
                        proto_type, _, payload_length = unpack_header(message)
                        if proto_type == MessageType.FRAME:
                            payload = message[HEADER_SIZE:HEADER_SIZE + payload_length]
                            frame_msg = FrameMessage.unpack(payload)

                            # Decode frame
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
        # Connect to relay
        if not await self.connect():
            print("Failed to connect. Check the session code and try again.")
            return

        self.running = True
        self._fps_start = time.time()

        # Start receive task
        receive_task = asyncio.create_task(self.receive_loop())

        print("Connected! Waiting for screen data...")
        print("Press ESC or close window to disconnect.")

        try:
            while self.running:
                # Handle PyGame events
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
╔══════════════════════════════════════════════════════════════╗
║           Remote Desktop - Viewer (Relay Mode)               ║
╠══════════════════════════════════════════════════════════════╣
║  Relay:  {args.relay:<52}║
║  Code:   {args.code:<52}║
║  Scale:  {args.scale:<52}║
╠══════════════════════════════════════════════════════════════╣
║  Controls:                                                   ║
║    - ESC or close window to disconnect                       ║
║    - Mouse and keyboard are sent to remote                   ║
╚══════════════════════════════════════════════════════════════╝
""")

    asyncio.run(run_relay_viewer(args.relay, args.code, args.scale))
