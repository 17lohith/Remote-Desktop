"""
Frame Decoder Module

Decompresses received frames for display.
Handles JPEG, PNG, and RAW formats.
"""

import io
import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class DecodedFrame:
    """A decoded frame ready for display."""
    data: np.ndarray      # RGB numpy array (height, width, 3)
    width: int
    height: int
    frame_number: int
    decode_time_ms: float


class FrameDecoder:
    """
    Decodes compressed frames received over the network.
    """

    def __init__(self):
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow is required for decoding. Install with: pip install Pillow")

        # Stats
        self._total_frames = 0
        self._total_decode_time = 0.0
        self._last_frame: Optional[DecodedFrame] = None

    def decode(self, data: bytes, frame_number: int = 0) -> DecodedFrame:
        """
        Decode compressed frame data.

        Args:
            data: Compressed image bytes (JPEG, PNG, or raw)
            frame_number: Frame sequence number

        Returns:
            DecodedFrame with RGB pixel data
        """
        start_time = time.perf_counter()

        try:
            # Try to decode as image (JPEG/PNG)
            buffer = io.BytesIO(data)
            img = Image.open(buffer)
            img = img.convert('RGB')  # Ensure RGB format
            rgb_array = np.array(img)
        except Exception as e:
            logger.error(f"Failed to decode frame: {e}")
            raise ValueError(f"Could not decode frame data: {e}")

        decode_time = (time.perf_counter() - start_time) * 1000

        # Update stats
        self._total_frames += 1
        self._total_decode_time += decode_time

        decoded = DecodedFrame(
            data=rgb_array,
            width=rgb_array.shape[1],
            height=rgb_array.shape[0],
            frame_number=frame_number,
            decode_time_ms=decode_time
        )

        self._last_frame = decoded

        logger.debug(
            f"Frame {frame_number} decoded: {decoded.width}x{decoded.height} "
            f"in {decode_time:.1f}ms"
        )

        return decoded

    def decode_from_message(self, frame_msg) -> DecodedFrame:
        """
        Decode a FrameMessage from the protocol.

        Args:
            frame_msg: FrameMessage object from protocol

        Returns:
            DecodedFrame with RGB pixel data
        """
        return self.decode(frame_msg.frame_data, frame_msg.frame_number)

    @property
    def last_frame(self) -> Optional[DecodedFrame]:
        """Get the last decoded frame (useful for display refresh)."""
        return self._last_frame

    @property
    def stats(self) -> dict:
        """Get decoding statistics."""
        if self._total_frames == 0:
            return {
                'total_frames': 0,
                'avg_decode_time_ms': 0
            }

        return {
            'total_frames': self._total_frames,
            'avg_decode_time_ms': self._total_decode_time / self._total_frames
        }

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._total_frames = 0
        self._total_decode_time = 0.0


class FrameBuffer:
    """
    Buffer for managing incoming frames.

    Handles frame ordering, dropping old frames, and providing
    the latest frame for display.
    """

    def __init__(self, max_size: int = 3):
        """
        Initialize frame buffer.

        Args:
            max_size: Maximum frames to buffer (older frames dropped)
        """
        self.max_size = max_size
        self._frames: list[DecodedFrame] = []
        self._last_displayed_frame: int = -1

    def add(self, frame: DecodedFrame) -> None:
        """Add a frame to the buffer."""
        # Insert in order by frame number
        insert_idx = len(self._frames)
        for i, f in enumerate(self._frames):
            if f.frame_number > frame.frame_number:
                insert_idx = i
                break

        self._frames.insert(insert_idx, frame)

        # Drop old frames if buffer is full
        while len(self._frames) > self.max_size:
            dropped = self._frames.pop(0)
            logger.debug(f"Dropped frame {dropped.frame_number} (buffer full)")

    def get_next(self) -> Optional[DecodedFrame]:
        """
        Get the next frame to display.

        Returns frames in order, skipping already-displayed frames.
        """
        for frame in self._frames:
            if frame.frame_number > self._last_displayed_frame:
                self._last_displayed_frame = frame.frame_number
                return frame
        return None

    def get_latest(self) -> Optional[DecodedFrame]:
        """
        Get the most recent frame, regardless of order.

        Use this for real-time display where latency matters more than smoothness.
        """
        if not self._frames:
            return None

        latest = max(self._frames, key=lambda f: f.frame_number)
        self._last_displayed_frame = latest.frame_number

        # Clear older frames
        self._frames = [f for f in self._frames if f.frame_number >= latest.frame_number]

        return latest

    def clear(self) -> None:
        """Clear all buffered frames."""
        self._frames.clear()
        self._last_displayed_frame = -1

    @property
    def size(self) -> int:
        """Current buffer size."""
        return len(self._frames)

    @property
    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return len(self._frames) == 0


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("Testing frame decoder...")

    # Create a test JPEG image
    from PIL import Image as PILImage

    test_img = PILImage.new('RGB', (1920, 1080), color=(100, 150, 200))

    # Encode to JPEG
    buffer = io.BytesIO()
    test_img.save(buffer, format='JPEG', quality=70)
    jpeg_data = buffer.getvalue()

    print(f"Test JPEG size: {len(jpeg_data)/1024:.1f}KB")

    # Decode
    decoder = FrameDecoder()

    for i in range(5):
        decoded = decoder.decode(jpeg_data, frame_number=i)
        print(f"Frame {i}: {decoded.width}x{decoded.height} in {decoded.decode_time_ms:.1f}ms")

    print(f"\nStats: {decoder.stats}")

    # Test frame buffer
    print("\nTesting frame buffer...")
    frame_buffer = FrameBuffer(max_size=3)

    for i in range(5):
        decoded = decoder.decode(jpeg_data, frame_number=i)
        frame_buffer.add(decoded)
        print(f"Added frame {i}, buffer size: {frame_buffer.size}")

    print(f"Latest frame: {frame_buffer.get_latest().frame_number}")
