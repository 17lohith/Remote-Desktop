#!/usr/bin/env python3
"""
View Remote Screen (via Relay)

Connect to a remote screen using a session code.

Usage:
    python view_screen.py --relay ws://relay-server.com:8765 --code ABC123
"""

import argparse
import asyncio
import logging
import sys

from relay.viewer import RelayViewer

# ---------------------------------------------------------------
# Default relay URL – change this when you deploy to EC2:
#   Local  : ws://127.0.0.1:8765
#   EC2    : ws://<EC2_PUBLIC_IP>:8765
# ---------------------------------------------------------------
DEFAULT_RELAY = "ws://127.0.0.1:8765"


def main():
    parser = argparse.ArgumentParser(
        description="View a remote screen via relay server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Connect with session code
    python view_screen.py --relay ws://relay.example.com:8765 --code ABC123

    # With smaller window
    python view_screen.py --relay ws://localhost:8765 --code ABC123 --scale 0.5
"""
    )
    parser.add_argument("--relay", default=DEFAULT_RELAY,
                       help=f"Relay server URL (default: {DEFAULT_RELAY})")
    parser.add_argument("--code", required=True,
                       help="6-character session code from host")
    parser.add_argument("--scale", type=float, default=1.0,
                       help="Display scale (0.5 = half size, default: 1.0)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    args = parser.parse_args()

    # Validate code format
    code = args.code.upper().strip()
    if len(code) != 6:
        print(f"❌ Invalid session code: '{args.code}'")
        print("   Session codes are 6 characters (e.g., ABC123)")
        sys.exit(1)

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           🖥️  Remote Desktop Viewer                          ║
╠══════════════════════════════════════════════════════════════╣
║  Connecting to: {args.relay:<44}║
║  Session Code:  {code:<44}║
╠══════════════════════════════════════════════════════════════╣
║  Controls:                                                   ║
║    - Mouse and keyboard are sent to remote                   ║
║    - Press ESC or close window to disconnect                 ║
╚══════════════════════════════════════════════════════════════╝
""")

    viewer = RelayViewer(args.relay, code, args.scale)

    async def run():
        await viewer.run()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n\n👋 Disconnected.")


if __name__ == "__main__":
    main()
