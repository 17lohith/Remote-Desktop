#!/usr/bin/env python3
"""
Remote Desktop GUI Viewer

PyGame-based viewer that displays the remote screen and captures input.

Usage:
    python viewer.py --host <IP> --port <PORT> [--scale 0.5]
"""

import asyncio
import logging
import sys
import os
import time
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import numpy as np

from client.connection import ClientConnection
from client.decoder import DecodedFrame
from common.protocol import MouseButton

logger = logging.getLogger(__name__)


class RemoteDesktopViewer:
    """
    PyGame-based GUI viewer for remote desktop.
    """

    def __init__(self, host: str, port: int, scale: float = 1.0):
        self.host = host
        self.port = port
        self.scale = scale

        self.client = ClientConnection()
        self.screen: Optional[pygame.Surface] = None
        self.running = False

        # Remote screen dimensions
        self.remote_width = 0
        self.remote_height = 0

        # Local display dimensions (after scaling)
        self.display_width = 0
        self.display_height = 0

        # Frame stats
        self.frame_count = 0
        self.last_frame_time = 0
        self.fps = 0.0

        # Latest frame surface for rendering
        self._latest_surface: Optional[pygame.Surface] = None
        self._frame_lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Connect to the remote host."""
        logger.info(f"Connecting to {self.host}:{self.port}...")

        if not await self.client.connect(self.host, self.port, "PyGameViewer"):
            logger.error("Failed to connect to host")
            return False

        # Get remote screen dimensions
        self.remote_width = self.client.connection_info.screen_width
        self.remote_height = self.client.connection_info.screen_height

        logger.info(f"Connected! Remote screen: {self.remote_width}x{self.remote_height}")
        return True

    def init_display(self) -> None:
        """Initialize PyGame display."""
        pygame.init()

        # Calculate display size with scaling
        self.display_width = int(self.remote_width * self.scale)
        self.display_height = int(self.remote_height * self.scale)

        # Create the display window
        self.screen = pygame.display.set_mode((self.display_width, self.display_height))
        pygame.display.set_caption(f"Remote Desktop - {self.host}:{self.port}")

        logger.info(f"Display initialized: {self.display_width}x{self.display_height} (scale: {self.scale})")

    def on_frame(self, frame: DecodedFrame) -> None:
        """Handle incoming frame - convert to PyGame surface."""
        try:
            # Convert numpy array to pygame surface
            # numpy array is (height, width, 3) RGB
            # pygame needs (width, height) so we swap axes
            surface = pygame.surfarray.make_surface(frame.data.swapaxes(0, 1))

            # Scale if needed
            if self.scale != 1.0:
                surface = pygame.transform.scale(surface, (self.display_width, self.display_height))

            self._latest_surface = surface

            # Update FPS counter
            self.frame_count += 1
            now = time.time()
            if now - self.last_frame_time >= 1.0:
                self.fps = self.frame_count / (now - self.last_frame_time)
                self.frame_count = 0
                self.last_frame_time = now
                pygame.display.set_caption(
                    f"Remote Desktop - {self.host}:{self.port} | {self.fps:.1f} FPS"
                )

        except Exception as e:
            logger.error(f"Error processing frame: {e}")

    def render(self) -> None:
        """Render the latest frame to the display."""
        if self._latest_surface and self.screen:
            self.screen.blit(self._latest_surface, (0, 0))
            pygame.display.flip()

    async def handle_events(self) -> bool:
        """Handle PyGame events. Returns False if should quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                # Send key down to remote
                await self.client.send_key_down(event.key, self._get_modifiers())

            elif event.type == pygame.KEYUP:
                await self.client.send_key_up(event.key, self._get_modifiers())

            elif event.type == pygame.MOUSEMOTION:
                # Scale mouse position to remote coordinates
                x, y = self._scale_mouse_pos(event.pos)
                await self.client.send_mouse_move(x, y)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                x, y = self._scale_mouse_pos(event.pos)
                button = self._map_mouse_button(event.button)
                await self.client.send_mouse_down(x, y, button)

            elif event.type == pygame.MOUSEBUTTONUP:
                x, y = self._scale_mouse_pos(event.pos)
                button = self._map_mouse_button(event.button)
                await self.client.send_mouse_up(x, y, button)

            elif event.type == pygame.MOUSEWHEEL:
                x, y = pygame.mouse.get_pos()
                x, y = self._scale_mouse_pos((x, y))
                await self.client.send_mouse_scroll(x, y, event.y * 3)  # Multiply for smoother scrolling

        return True

    def _scale_mouse_pos(self, pos: tuple) -> tuple:
        """Scale local mouse position to remote coordinates."""
        x = int(pos[0] / self.scale)
        y = int(pos[1] / self.scale)
        return x, y

    def _get_modifiers(self) -> int:
        """Get current keyboard modifiers."""
        mods = pygame.key.get_mods()
        modifiers = 0
        if mods & pygame.KMOD_SHIFT:
            modifiers |= 0x01
        if mods & pygame.KMOD_CTRL:
            modifiers |= 0x02
        if mods & pygame.KMOD_ALT:
            modifiers |= 0x04
        if mods & pygame.KMOD_META:  # Command key on Mac
            modifiers |= 0x08
        return modifiers

    def _map_mouse_button(self, button: int) -> MouseButton:
        """Map PyGame mouse button to protocol button."""
        if button == 1:
            return MouseButton.LEFT
        elif button == 2:
            return MouseButton.MIDDLE
        elif button == 3:
            return MouseButton.RIGHT
        return MouseButton.LEFT

    async def run(self) -> None:
        """Main viewer loop."""
        # Connect to host
        if not await self.connect():
            return

        # Initialize display
        self.init_display()

        # Set up frame callback
        self.client.on_frame(self.on_frame)

        # Start receiving frames in background
        receive_task = asyncio.create_task(self.client.start_receiving())

        self.running = True
        self.last_frame_time = time.time()

        logger.info("Viewer running. Press ESC or close window to quit.")

        try:
            while self.running:
                # Handle PyGame events
                if not await self.handle_events():
                    break

                # Render latest frame
                self.render()

                # Small delay to prevent CPU spinning
                await asyncio.sleep(0.001)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Viewer error: {e}")
        finally:
            self.running = False
            await self.client.disconnect()
            pygame.quit()
            logger.info("Viewer closed")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Remote Desktop Viewer")
    parser.add_argument("--host", default="localhost", help="Host to connect to")
    parser.add_argument("--port", type=int, default=9001, help="Port to connect to")
    parser.add_argument("--scale", type=float, default=1.0, help="Display scale (0.5 = half size)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"""
╔══════════════════════════════════════════════════════════╗
║         Remote Desktop - GUI Viewer                      ║
╚══════════════════════════════════════════════════════════╝

Connecting to ws://{args.host}:{args.port}...
Scale: {args.scale}x

Controls:
  - ESC or close window to quit
  - Mouse and keyboard are sent to remote host
""")

    viewer = RemoteDesktopViewer(args.host, args.port, args.scale)
    await viewer.run()


if __name__ == "__main__":
    asyncio.run(main())
