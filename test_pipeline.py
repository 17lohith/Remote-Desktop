#!/usr/bin/env python3
"""
Test the full capture → encode → decode pipeline.

This simulates the data flow that will happen during a remote session:
1. Capture screen on host
2. Encode frame for transmission
3. Decode frame on client
4. Measure performance

Usage:
    python test_pipeline.py [--frames N] [--quality Q] [--save]
"""

import argparse
import logging
import time
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from host.capture import ScreenCapture, FrameRateLimiter
from host.encoder import FrameEncoder, EncodingFormat
from client.decoder import FrameDecoder, FrameBuffer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def test_capture_only(num_frames: int = 30):
    """Test screen capture performance."""
    print("\n=== Screen Capture Test ===")

    capture = ScreenCapture(target_fps=30)
    print(f"Screen size: {capture.screen_info.width}x{capture.screen_info.height}")

    times = []
    for i in range(num_frames):
        start = time.perf_counter()
        frame = capture.grab()
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

        if (i + 1) % 10 == 0:
            print(f"  Captured {i + 1}/{num_frames} frames...")

    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)

    print(f"\nCapture Results:")
    print(f"  Frames: {num_frames}")
    print(f"  Avg time: {avg_time:.1f}ms")
    print(f"  Min time: {min_time:.1f}ms")
    print(f"  Max time: {max_time:.1f}ms")
    print(f"  Max FPS: {1000/avg_time:.1f}")

    return avg_time


def test_encode_only(num_frames: int = 30, quality: int = 70):
    """Test encoding performance."""
    print(f"\n=== Encoding Test (quality={quality}) ===")

    capture = ScreenCapture(target_fps=30)
    encoder = FrameEncoder(quality=quality)

    # Capture one frame to encode repeatedly
    frame = capture.grab()
    original_size = frame.data.nbytes / 1024  # KB

    times = []
    sizes = []
    for i in range(num_frames):
        start = time.perf_counter()
        encoded = encoder.encode(frame)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
        sizes.append(encoded.compressed_size / 1024)  # KB

        if (i + 1) % 10 == 0:
            print(f"  Encoded {i + 1}/{num_frames} frames...")

    avg_time = sum(times) / len(times)
    avg_size = sum(sizes) / len(sizes)

    print(f"\nEncode Results:")
    print(f"  Original size: {original_size:.1f}KB")
    print(f"  Compressed size: {avg_size:.1f}KB")
    print(f"  Compression ratio: {original_size/avg_size:.1f}x")
    print(f"  Avg encode time: {avg_time:.1f}ms")
    print(f"  Max encode FPS: {1000/avg_time:.1f}")

    return avg_time, avg_size


def test_decode_only(num_frames: int = 30, quality: int = 70):
    """Test decoding performance."""
    print(f"\n=== Decoding Test ===")

    capture = ScreenCapture(target_fps=30)
    encoder = FrameEncoder(quality=quality)
    decoder = FrameDecoder()

    # Capture and encode one frame
    frame = capture.grab()
    encoded = encoder.encode(frame)

    times = []
    for i in range(num_frames):
        start = time.perf_counter()
        decoded = decoder.decode(encoded.data, frame_number=i)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

        if (i + 1) % 10 == 0:
            print(f"  Decoded {i + 1}/{num_frames} frames...")

    avg_time = sum(times) / len(times)

    print(f"\nDecode Results:")
    print(f"  Avg decode time: {avg_time:.1f}ms")
    print(f"  Max decode FPS: {1000/avg_time:.1f}")

    return avg_time


def test_full_pipeline(num_frames: int = 30, quality: int = 70, save_sample: bool = False):
    """Test the complete capture → encode → decode pipeline."""
    print(f"\n=== Full Pipeline Test (quality={quality}) ===")

    capture = ScreenCapture(target_fps=30)
    encoder = FrameEncoder(quality=quality)
    decoder = FrameDecoder()
    rate_limiter = FrameRateLimiter(target_fps=30)

    print(f"Screen size: {capture.screen_info.width}x{capture.screen_info.height}")

    capture_times = []
    encode_times = []
    decode_times = []
    total_times = []
    sizes = []

    for i in range(num_frames):
        total_start = time.perf_counter()

        # 1. Capture
        cap_start = time.perf_counter()
        frame = capture.grab()
        capture_times.append((time.perf_counter() - cap_start) * 1000)

        # 2. Encode
        enc_start = time.perf_counter()
        encoded = encoder.encode(frame)
        encode_times.append((time.perf_counter() - enc_start) * 1000)
        sizes.append(encoded.compressed_size / 1024)

        # 3. Decode
        dec_start = time.perf_counter()
        decoded = decoder.decode(encoded.data, frame_number=i)
        decode_times.append((time.perf_counter() - dec_start) * 1000)

        total_times.append((time.perf_counter() - total_start) * 1000)

        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{num_frames} frames...")

        # Save first frame as sample
        if save_sample and i == 0:
            from PIL import Image
            img = Image.fromarray(decoded.data)
            img.save("sample_frame.jpg", quality=90)
            print(f"  Saved sample frame to sample_frame.jpg")

    # Calculate statistics
    avg_capture = sum(capture_times) / len(capture_times)
    avg_encode = sum(encode_times) / len(encode_times)
    avg_decode = sum(decode_times) / len(decode_times)
    avg_total = sum(total_times) / len(total_times)
    avg_size = sum(sizes) / len(sizes)

    # Calculate bandwidth requirements
    bandwidth_30fps = avg_size * 30 * 8 / 1000  # Mbps at 30 FPS

    print(f"\n{'='*50}")
    print(f"Pipeline Results ({num_frames} frames)")
    print(f"{'='*50}")
    print(f"\nTiming (avg):")
    print(f"  Capture:  {avg_capture:6.1f}ms")
    print(f"  Encode:   {avg_encode:6.1f}ms")
    print(f"  Decode:   {avg_decode:6.1f}ms")
    print(f"  Total:    {avg_total:6.1f}ms")
    print(f"\nPerformance:")
    print(f"  Max theoretical FPS: {1000/avg_total:.1f}")
    print(f"  Target 30 FPS budget: 33.3ms (current: {avg_total:.1f}ms) {'✓' if avg_total < 33.3 else '✗'}")
    print(f"\nBandwidth:")
    print(f"  Avg frame size: {avg_size:.1f}KB")
    print(f"  @ 30 FPS: {bandwidth_30fps:.1f} Mbps")
    print(f"  @ 60 FPS: {bandwidth_30fps*2:.1f} Mbps")

    return {
        'avg_capture_ms': avg_capture,
        'avg_encode_ms': avg_encode,
        'avg_decode_ms': avg_decode,
        'avg_total_ms': avg_total,
        'avg_size_kb': avg_size,
        'bandwidth_30fps_mbps': bandwidth_30fps,
        'max_fps': 1000 / avg_total
    }


def test_quality_comparison():
    """Compare different quality levels."""
    print("\n=== Quality Comparison ===")

    capture = ScreenCapture(target_fps=30)
    frame = capture.grab()
    original_size = frame.data.nbytes / 1024

    print(f"Original frame size: {original_size:.1f}KB")
    print(f"{'Quality':<10} {'Size (KB)':<12} {'Ratio':<10} {'30fps BW':<12}")
    print("-" * 50)

    for quality in [30, 50, 70, 85, 95]:
        encoder = FrameEncoder(quality=quality)
        encoded = encoder.encode(frame)
        size_kb = encoded.compressed_size / 1024
        ratio = original_size / size_kb
        bandwidth = size_kb * 30 * 8 / 1000  # Mbps

        print(f"{quality:<10} {size_kb:<12.1f} {ratio:<10.1f}x {bandwidth:<12.1f} Mbps")


def main():
    parser = argparse.ArgumentParser(description="Test capture/encode/decode pipeline")
    parser.add_argument("--frames", type=int, default=30, help="Number of frames to test")
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality (1-100)")
    parser.add_argument("--save", action="store_true", help="Save sample frame")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════════╗
║         Remote Desktop - Pipeline Test                   ║
╚══════════════════════════════════════════════════════════╝
""")

    try:
        if args.all:
            test_capture_only(args.frames)
            test_encode_only(args.frames, args.quality)
            test_decode_only(args.frames, args.quality)
            test_quality_comparison()

        results = test_full_pipeline(args.frames, args.quality, args.save)

        print(f"\n{'='*50}")
        print("SUMMARY")
        print(f"{'='*50}")
        if results['max_fps'] >= 30:
            print("✓ Pipeline can sustain 30 FPS")
        else:
            print(f"✗ Pipeline limited to {results['max_fps']:.1f} FPS")

        if results['bandwidth_30fps_mbps'] < 10:
            print(f"✓ Bandwidth reasonable ({results['bandwidth_30fps_mbps']:.1f} Mbps)")
        else:
            print(f"⚠ High bandwidth ({results['bandwidth_30fps_mbps']:.1f} Mbps) - consider lower quality")

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
