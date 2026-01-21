"""
Screen Capture Module

Captures the screen using macOS Quartz APIs.
Optimized for continuous capture at 30+ FPS.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np

# macOS Quartz APIs
try:
    import Quartz
    from Quartz import (
        CGWindowListCreateImage,
        CGRectInfinite,
        CGRectMake,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
        kCGWindowImageDefault,
        kCGWindowImageBoundsIgnoreFraming,
        CGImageGetWidth,
        CGImageGetHeight,
        CGImageGetBytesPerRow,
        CGImageGetDataProvider,
        CGDataProviderCopyData,
        CGMainDisplayID,
        CGDisplayBounds,
    )
    QUARTZ_AVAILABLE = True
except ImportError:
    QUARTZ_AVAILABLE = False

# Fallback for non-macOS or missing PyObjC
try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ScreenInfo:
    """Information about the captured screen."""
    width: int
    height: int
    scale_factor: float = 1.0  # Retina displays have scale > 1


@dataclass
class Frame:
    """A captured screen frame."""
    data: np.ndarray  # RGB numpy array (height, width, 3)
    width: int
    height: int
    timestamp: float
    frame_number: int

    @property
    def shape(self) -> Tuple[int, int, int]:
        return self.data.shape


class ScreenCapture:
    """
    High-performance screen capture for macOS.

    Uses Quartz APIs for native capture, falls back to PIL if unavailable.
    """

    def __init__(self, target_fps: int = 30, display_id: Optional[int] = None):
        """
        Initialize screen capture.

        Args:
            target_fps: Target frames per second
            display_id: Specific display to capture (None = main display)
        """
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.display_id = display_id or (CGMainDisplayID() if QUARTZ_AVAILABLE else 0)

        self._frame_number = 0
        self._last_capture_time = 0.0
        self._screen_info: Optional[ScreenInfo] = None

        # Determine capture method
        if QUARTZ_AVAILABLE:
            self._capture_method = self._capture_quartz
            logger.info("Using Quartz capture (native macOS)")
        elif PIL_AVAILABLE:
            self._capture_method = self._capture_pil
            logger.info("Using PIL capture (fallback)")
        else:
            raise RuntimeError("No capture method available. Install PyObjC or Pillow.")

        # Get initial screen info
        self._update_screen_info()

    def _update_screen_info(self) -> None:
        """Update screen dimensions."""
        if QUARTZ_AVAILABLE:
            bounds = CGDisplayBounds(self.display_id)
            self._screen_info = ScreenInfo(
                width=int(bounds.size.width),
                height=int(bounds.size.height),
                scale_factor=1.0  # Will be detected from actual capture
            )
        else:
            # Fallback: capture one frame to get dimensions
            from PIL import ImageGrab
            img = ImageGrab.grab()
            self._screen_info = ScreenInfo(
                width=img.width,
                height=img.height
            )

    @property
    def screen_info(self) -> ScreenInfo:
        """Get current screen information."""
        if self._screen_info is None:
            self._update_screen_info()
        return self._screen_info

    def grab(self) -> Frame:
        """
        Capture the current screen.

        Returns:
            Frame object with RGB pixel data
        """
        start_time = time.perf_counter()

        # Capture using selected method
        rgb_array = self._capture_method()

        # Update frame counter
        self._frame_number += 1

        frame = Frame(
            data=rgb_array,
            width=rgb_array.shape[1],
            height=rgb_array.shape[0],
            timestamp=start_time,
            frame_number=self._frame_number
        )

        # Update screen info if dimensions changed
        if (self._screen_info is None or
            self._screen_info.width != frame.width or
            self._screen_info.height != frame.height):
            self._screen_info = ScreenInfo(
                width=frame.width,
                height=frame.height
            )

        capture_time = time.perf_counter() - start_time
        logger.debug(f"Frame {self._frame_number} captured in {capture_time*1000:.1f}ms")

        return frame

    async def grab_async(self) -> Frame:
        """
        Async wrapper for grab().
        Runs capture in thread pool to avoid blocking.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.grab)

    def _capture_quartz(self) -> np.ndarray:
        """Capture screen using Quartz APIs."""
        # Capture entire screen
        image = CGWindowListCreateImage(
            CGRectInfinite,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
            kCGWindowImageDefault
        )

        if image is None:
            raise RuntimeError("Failed to capture screen (CGWindowListCreateImage returned None)")

        # Get image dimensions
        width = CGImageGetWidth(image)
        height = CGImageGetHeight(image)
        bytes_per_row = CGImageGetBytesPerRow(image)

        # Get raw pixel data
        data_provider = CGImageGetDataProvider(image)
        data = CGDataProviderCopyData(data_provider)

        # Convert to numpy array
        # Quartz returns BGRA format
        arr = np.frombuffer(data, dtype=np.uint8)
        arr = arr.reshape((height, bytes_per_row // 4, 4))

        # Trim to actual width (bytes_per_row may include padding)
        arr = arr[:, :width, :]

        # Convert BGRA to RGB
        rgb = arr[:, :, [2, 1, 0]]

        return rgb.copy()  # Copy to ensure contiguous memory

    def _capture_pil(self) -> np.ndarray:
        """Capture screen using PIL (fallback)."""
        from PIL import ImageGrab
        img = ImageGrab.grab()
        return np.array(img)

    def capture_region(self, x: int, y: int, width: int, height: int) -> Frame:
        """
        Capture a specific region of the screen.

        Args:
            x, y: Top-left corner
            width, height: Region dimensions

        Returns:
            Frame with captured region
        """
        if QUARTZ_AVAILABLE:
            rect = CGRectMake(x, y, width, height)
            image = CGWindowListCreateImage(
                rect,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowImageBoundsIgnoreFraming
            )

            if image is None:
                raise RuntimeError("Failed to capture region")

            img_width = CGImageGetWidth(image)
            img_height = CGImageGetHeight(image)
            bytes_per_row = CGImageGetBytesPerRow(image)

            data_provider = CGImageGetDataProvider(image)
            data = CGDataProviderCopyData(data_provider)

            arr = np.frombuffer(data, dtype=np.uint8)
            arr = arr.reshape((img_height, bytes_per_row // 4, 4))
            arr = arr[:, :img_width, :]
            rgb = arr[:, :, [2, 1, 0]].copy()
        else:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(x, y, x + width, y + height))
            rgb = np.array(img)

        self._frame_number += 1
        return Frame(
            data=rgb,
            width=rgb.shape[1],
            height=rgb.shape[0],
            timestamp=time.perf_counter(),
            frame_number=self._frame_number
        )


class FrameRateLimiter:
    """Utility to maintain consistent frame rate."""

    def __init__(self, target_fps: int = 30):
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self._last_frame_time = 0.0

    def wait(self) -> float:
        """
        Wait until next frame should be captured.
        Returns actual time since last frame.
        """
        now = time.perf_counter()
        elapsed = now - self._last_frame_time

        if elapsed < self.frame_interval:
            sleep_time = self.frame_interval - elapsed
            time.sleep(sleep_time)
            now = time.perf_counter()
            elapsed = now - self._last_frame_time

        self._last_frame_time = now
        return elapsed

    async def wait_async(self) -> float:
        """Async version of wait()."""
        import asyncio
        now = time.perf_counter()
        elapsed = now - self._last_frame_time

        if elapsed < self.frame_interval:
            sleep_time = self.frame_interval - elapsed
            await asyncio.sleep(sleep_time)
            now = time.perf_counter()
            elapsed = now - self._last_frame_time

        self._last_frame_time = now
        return elapsed


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("Testing screen capture...")
    capture = ScreenCapture(target_fps=30)

    print(f"Screen: {capture.screen_info.width}x{capture.screen_info.height}")

    # Capture a few frames
    times = []
    for i in range(10):
        start = time.perf_counter()
        frame = capture.grab()
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"Frame {i+1}: {frame.width}x{frame.height}, {elapsed*1000:.1f}ms")

    avg_time = sum(times) / len(times)
    print(f"\nAverage capture time: {avg_time*1000:.1f}ms")
    print(f"Max theoretical FPS: {1/avg_time:.1f}")
