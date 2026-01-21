"""
Frame Encoder Module

Compresses captured frames for network transmission.
Supports JPEG encoding with configurable quality.
"""

import io
import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import IntEnum

import numpy as np

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


class EncodingFormat(IntEnum):
    """Supported encoding formats."""
    JPEG = 1
    PNG = 2  # Lossless but slower
    RAW = 3  # No compression (for debugging)


@dataclass
class EncodedFrame:
    """A compressed frame ready for transmission."""
    data: bytes          # Compressed image data
    width: int
    height: int
    format: EncodingFormat
    quality: int
    frame_number: int
    original_size: int   # Size before compression
    compressed_size: int # Size after compression
    encode_time_ms: float

    @property
    def compression_ratio(self) -> float:
        """Compression ratio (higher = more compression)."""
        if self.compressed_size == 0:
            return 0
        return self.original_size / self.compressed_size


class FrameEncoder:
    """
    Encodes frames for network transmission.

    Supports adaptive quality based on target bandwidth.
    """

    def __init__(
        self,
        format: EncodingFormat = EncodingFormat.JPEG,
        quality: int = 70,
        min_quality: int = 30,
        max_quality: int = 95
    ):
        """
        Initialize encoder.

        Args:
            format: Encoding format (JPEG recommended for MVP)
            quality: Initial quality (1-100 for JPEG)
            min_quality: Minimum quality for adaptive mode
            max_quality: Maximum quality for adaptive mode
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow is required for encoding. Install with: pip install Pillow")

        self.format = format
        self.quality = quality
        self.min_quality = min_quality
        self.max_quality = max_quality

        # Stats tracking
        self._total_frames = 0
        self._total_original_bytes = 0
        self._total_compressed_bytes = 0
        self._total_encode_time = 0.0

    def encode(self, frame) -> EncodedFrame:
        """
        Encode a frame.

        Args:
            frame: Frame object from capture module

        Returns:
            EncodedFrame with compressed data
        """
        start_time = time.perf_counter()

        # Get RGB data
        rgb_data = frame.data
        height, width = rgb_data.shape[:2]
        original_size = rgb_data.nbytes

        # Create PIL Image
        img = Image.fromarray(rgb_data, mode='RGB')

        # Encode based on format
        buffer = io.BytesIO()

        if self.format == EncodingFormat.JPEG:
            img.save(buffer, format='JPEG', quality=self.quality, optimize=False)
        elif self.format == EncodingFormat.PNG:
            img.save(buffer, format='PNG', compress_level=6)
        elif self.format == EncodingFormat.RAW:
            buffer.write(rgb_data.tobytes())
        else:
            raise ValueError(f"Unknown format: {self.format}")

        compressed_data = buffer.getvalue()
        compressed_size = len(compressed_data)

        encode_time = (time.perf_counter() - start_time) * 1000

        # Update stats
        self._total_frames += 1
        self._total_original_bytes += original_size
        self._total_compressed_bytes += compressed_size
        self._total_encode_time += encode_time

        encoded = EncodedFrame(
            data=compressed_data,
            width=width,
            height=height,
            format=self.format,
            quality=self.quality,
            frame_number=frame.frame_number,
            original_size=original_size,
            compressed_size=compressed_size,
            encode_time_ms=encode_time
        )

        logger.debug(
            f"Frame {frame.frame_number} encoded: {original_size/1024:.1f}KB → "
            f"{compressed_size/1024:.1f}KB ({encoded.compression_ratio:.1f}x) "
            f"in {encode_time:.1f}ms"
        )

        return encoded

    def encode_raw(self, rgb_array: np.ndarray, frame_number: int = 0) -> EncodedFrame:
        """
        Encode a raw numpy array.

        Args:
            rgb_array: RGB numpy array (height, width, 3)
            frame_number: Frame sequence number

        Returns:
            EncodedFrame with compressed data
        """
        # Create a mock frame object
        class MockFrame:
            def __init__(self, data, num):
                self.data = data
                self.frame_number = num

        return self.encode(MockFrame(rgb_array, frame_number))

    def set_quality(self, quality: int) -> None:
        """Set encoding quality (1-100)."""
        self.quality = max(self.min_quality, min(self.max_quality, quality))
        logger.debug(f"Quality set to {self.quality}")

    def adjust_quality_for_bandwidth(self, target_kbps: int, current_fps: int) -> None:
        """
        Adjust quality to hit target bandwidth.

        Args:
            target_kbps: Target bandwidth in kilobits per second
            current_fps: Current frame rate
        """
        if self._total_frames == 0:
            return

        # Calculate current bandwidth
        avg_frame_size = self._total_compressed_bytes / self._total_frames
        current_kbps = (avg_frame_size * 8 * current_fps) / 1000

        # Adjust quality
        if current_kbps > target_kbps * 1.1:  # Too high
            self.quality = max(self.min_quality, self.quality - 5)
            logger.debug(f"Reducing quality to {self.quality} (bandwidth: {current_kbps:.0f} kbps)")
        elif current_kbps < target_kbps * 0.8:  # Too low
            self.quality = min(self.max_quality, self.quality + 5)
            logger.debug(f"Increasing quality to {self.quality} (bandwidth: {current_kbps:.0f} kbps)")

    @property
    def stats(self) -> dict:
        """Get encoding statistics."""
        if self._total_frames == 0:
            return {
                'total_frames': 0,
                'avg_compression_ratio': 0,
                'avg_encode_time_ms': 0,
                'avg_frame_size_kb': 0
            }

        return {
            'total_frames': self._total_frames,
            'avg_compression_ratio': self._total_original_bytes / max(1, self._total_compressed_bytes),
            'avg_encode_time_ms': self._total_encode_time / self._total_frames,
            'avg_frame_size_kb': (self._total_compressed_bytes / self._total_frames) / 1024
        }

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._total_frames = 0
        self._total_original_bytes = 0
        self._total_compressed_bytes = 0
        self._total_encode_time = 0.0


class RegionEncoder:
    """
    Encodes specific regions of a frame at different quality levels.
    Used for AI-enhanced encoding where cursor area gets higher quality.
    """

    def __init__(self, base_quality: int = 50, focus_quality: int = 85):
        """
        Initialize region encoder.

        Args:
            base_quality: Quality for background regions
            focus_quality: Quality for focus regions (cursor, active UI)
        """
        self.base_encoder = FrameEncoder(quality=base_quality)
        self.focus_encoder = FrameEncoder(quality=focus_quality)

    def encode_with_focus(
        self,
        frame,
        focus_regions: list[Tuple[int, int, int, int]]  # [(x, y, w, h), ...]
    ) -> Tuple[EncodedFrame, list[EncodedFrame]]:
        """
        Encode frame with high-quality focus regions.

        Args:
            frame: Full frame from capture
            focus_regions: List of (x, y, width, height) regions to encode at high quality

        Returns:
            (base_encoded, [focus_encoded_1, focus_encoded_2, ...])
        """
        # Encode full frame at base quality
        base_encoded = self.base_encoder.encode(frame)

        # Encode each focus region at high quality
        focus_encoded = []
        for x, y, w, h in focus_regions:
            # Extract region
            region_data = frame.data[y:y+h, x:x+w].copy()

            # Create mock frame for region
            class RegionFrame:
                def __init__(self, data, num):
                    self.data = data
                    self.frame_number = num

            region = RegionFrame(region_data, frame.frame_number)
            encoded = self.focus_encoder.encode(region)
            focus_encoded.append(encoded)

        return base_encoded, focus_encoded


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("Testing frame encoder...")

    # Create test image
    test_image = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)

    class MockFrame:
        def __init__(self, data):
            self.data = data
            self.frame_number = 1

    frame = MockFrame(test_image)

    # Test different quality levels
    for quality in [30, 50, 70, 90]:
        encoder = FrameEncoder(quality=quality)
        encoded = encoder.encode(frame)
        print(f"Quality {quality}: {encoded.compressed_size/1024:.1f}KB "
              f"({encoded.compression_ratio:.1f}x compression) "
              f"in {encoded.encode_time_ms:.1f}ms")
