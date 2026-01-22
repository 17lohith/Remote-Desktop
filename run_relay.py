#!/usr/bin/env python3
"""
Run Relay Server

Deploy this on a public server (cloud VPS, etc.) to enable
remote desktop connections across the internet.

Usage:
    python run_relay.py [--port 8765]
"""

import argparse
import asyncio
import logging

from relay.server import RelayServer


def main():
    parser = argparse.ArgumentParser(description="Remote Desktop Relay Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           Remote Desktop - Relay Server                      ║
╠══════════════════════════════════════════════════════════════╣
║  This server enables connections across the internet.        ║
║                                                              ║
║  Deploy on a public server and share the URL:                ║
║  ws://<your-server-ip>:{args.port:<43}║
╠══════════════════════════════════════════════════════════════╣
║  Listening on: {args.host}:{args.port:<43}║
╠══════════════════════════════════════════════════════════════╣
║  Press Ctrl+C to stop                                        ║
╚══════════════════════════════════════════════════════════════╝
""")

    server = RelayServer(args.host, args.port)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
