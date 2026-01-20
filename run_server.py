#!/usr/bin/env python3
"""
Run the Signaling Server

Usage:
    python run_server.py [--host HOST] [--port PORT]

Example:
    python run_server.py --port 9000
"""

import argparse
import asyncio
import logging
import signal
import sys

from common.config import SignalingConfig
from signaling.server import SignalingServer


def parse_args():
    parser = argparse.ArgumentParser(description="Remote Desktop Signaling Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=9000, help="Port to listen on (default: 9000)")
    parser.add_argument("--timeout", type=int, default=60, help="Session timeout in seconds (default: 60)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


async def main():
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Create config
    config = SignalingConfig(
        host=args.host,
        port=args.port,
        session_timeout=args.timeout
    )

    # Create server
    server = SignalingServer(config)

    # Handle shutdown gracefully
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def shutdown_handler():
        logging.info("Shutdown signal received")
        stop_event.set()

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_handler)

    # Start server
    print(f"""
╔══════════════════════════════════════════════════════════╗
║         Remote Desktop - Signaling Server                ║
╠══════════════════════════════════════════════════════════╣
║  Listening on: {args.host}:{args.port:<28}║
║  Session timeout: {args.timeout} seconds{' ' * (28 - len(str(args.timeout)))}║
╠══════════════════════════════════════════════════════════╣
║  Press Ctrl+C to stop                                    ║
╚══════════════════════════════════════════════════════════╝
""")

    try:
        # Run server until stop signal
        server_task = asyncio.create_task(server.start())
        await stop_event.wait()
        await server.stop()
    except Exception as e:
        logging.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
