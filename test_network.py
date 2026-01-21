#!/usr/bin/env python3
"""
Test Network Streaming

Tests the full network pipeline:
1. Start host server (captures and streams screen)
2. Start client (connects and receives frames)
3. Measure performance

Usage:
    python test_network.py [--duration SECONDS] [--quality QUALITY]
"""

import asyncio
import logging
import time
import sys
import os
import signal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from host.server import HostStreamingServer
from client.connection import ClientConnection
from common.config import HostConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def run_server(port: int, fps: int, quality: int, ready_event: asyncio.Event):
    """Run the host server."""
    config = HostConfig(
        capture_fps=fps,
        jpeg_quality=quality
    )
    server = HostStreamingServer(config)

    # Signal that server is ready
    ready_event.set()

    try:
        await server.start("127.0.0.1", port)
    except asyncio.CancelledError:
        await server.stop()


async def run_client(host: str, port: int, duration: int):
    """Run the client and collect stats."""
    client = ClientConnection()

    frames_received = []
    frame_sizes = []
    decode_times = []

    def on_frame(frame):
        frames_received.append(time.time())
        decode_times.append(frame.decode_time_ms)

    client.on_frame(on_frame)

    # Connect
    if not await client.connect(host, port, "TestClient"):
        print("Failed to connect to host!")
        return None

    print(f"Connected to host! Screen: {client.connection_info.screen_width}x{client.connection_info.screen_height}")

    # Receive frames for the duration
    start_time = time.time()
    receive_task = asyncio.create_task(client.start_receiving())

    try:
        await asyncio.sleep(duration)
    except asyncio.CancelledError:
        pass

    await client.disconnect()

    # Calculate stats
    elapsed = time.time() - start_time
    total_frames = len(frames_received)

    if total_frames > 1:
        # Calculate actual FPS from frame timestamps
        frame_intervals = []
        for i in range(1, len(frames_received)):
            frame_intervals.append(frames_received[i] - frames_received[i-1])
        avg_interval = sum(frame_intervals) / len(frame_intervals)
        actual_fps = 1.0 / avg_interval if avg_interval > 0 else 0
    else:
        actual_fps = 0

    avg_decode_time = sum(decode_times) / len(decode_times) if decode_times else 0

    return {
        'duration': elapsed,
        'total_frames': total_frames,
        'actual_fps': actual_fps,
        'avg_decode_time_ms': avg_decode_time,
        'decoder_stats': client.decoder.stats
    }


async def test_network_streaming(duration: int = 10, fps: int = 30, quality: int = 70):
    """Run the full network streaming test."""
    print(f"""
╔══════════════════════════════════════════════════════════╗
║         Remote Desktop - Network Test                    ║
╚══════════════════════════════════════════════════════════╝

Configuration:
  - Target FPS: {fps}
  - JPEG Quality: {quality}
  - Test Duration: {duration}s

""")

    port = 9099  # Use a test port
    ready_event = asyncio.Event()

    # Start server in background
    server_task = asyncio.create_task(run_server(port, fps, quality, ready_event))

    # Wait for server to be ready
    await asyncio.wait_for(ready_event.wait(), timeout=5.0)
    await asyncio.sleep(0.5)  # Give server time to fully start

    print("Host server started. Starting client...")

    # Run client
    stats = await run_client("127.0.0.1", port, duration)

    # Stop server
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

    if stats:
        print(f"""
{'='*60}
NETWORK STREAMING RESULTS
{'='*60}

Duration: {stats['duration']:.1f}s
Total Frames Received: {stats['total_frames']}
Actual FPS: {stats['actual_fps']:.1f}
Avg Decode Time: {stats['avg_decode_time_ms']:.1f}ms

Target FPS: {fps}
FPS Achievement: {(stats['actual_fps']/fps)*100:.1f}%

{'='*60}
""")
        if stats['actual_fps'] >= fps * 0.8:
            print("✓ Network streaming is working well!")
        elif stats['actual_fps'] >= fps * 0.5:
            print("⚠ Network streaming is working but below target FPS")
        else:
            print("✗ Network streaming has performance issues")

        return stats
    else:
        print("✗ Test failed - could not connect")
        return None


async def test_latency(iterations: int = 50):
    """Test round-trip latency."""
    print(f"""
╔══════════════════════════════════════════════════════════╗
║         Remote Desktop - Latency Test                    ║
╚══════════════════════════════════════════════════════════╝

Testing frame delivery latency over {iterations} frames...
""")

    port = 9098
    ready_event = asyncio.Event()

    # Start server
    server_task = asyncio.create_task(run_server(port, 60, 70, ready_event))
    await asyncio.wait_for(ready_event.wait(), timeout=5.0)
    await asyncio.sleep(0.5)

    client = ClientConnection()

    latencies = []
    frame_received_event = asyncio.Event()
    last_frame_time = [0]

    def on_frame(frame):
        last_frame_time[0] = time.perf_counter()
        frame_received_event.set()

    client.on_frame(on_frame)

    if await client.connect("127.0.0.1", port, "LatencyTest"):
        # Start receiving
        receive_task = asyncio.create_task(client.start_receiving())

        # Measure latency for each frame
        for i in range(iterations):
            frame_received_event.clear()
            start = time.perf_counter()

            try:
                await asyncio.wait_for(frame_received_event.wait(), timeout=1.0)
                latency = (last_frame_time[0] - start) * 1000
                latencies.append(latency)
            except asyncio.TimeoutError:
                pass

        await client.disconnect()

    # Stop server
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        min_latency = min(latencies)
        max_latency = max(latencies)

        print(f"""
{'='*60}
LATENCY RESULTS
{'='*60}

Frames Measured: {len(latencies)}
Average Latency: {avg_latency:.1f}ms
Min Latency: {min_latency:.1f}ms
Max Latency: {max_latency:.1f}ms

{'='*60}
""")
        if avg_latency < 50:
            print("✓ Excellent latency!")
        elif avg_latency < 100:
            print("✓ Good latency")
        elif avg_latency < 200:
            print("⚠ Acceptable latency")
        else:
            print("✗ High latency - may affect user experience")

        return {'avg': avg_latency, 'min': min_latency, 'max': max_latency}

    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test network streaming")
    parser.add_argument("--duration", type=int, default=10, help="Test duration in seconds")
    parser.add_argument("--fps", type=int, default=30, help="Target FPS")
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality")
    parser.add_argument("--latency", action="store_true", help="Run latency test instead")
    args = parser.parse_args()

    try:
        if args.latency:
            asyncio.run(test_latency())
        else:
            asyncio.run(test_network_streaming(args.duration, args.fps, args.quality))
    except KeyboardInterrupt:
        print("\nTest interrupted")


if __name__ == "__main__":
    main()
