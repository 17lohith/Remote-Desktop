#!/usr/bin/env python3
"""
Share Your Screen (via Relay)

Run this to share your screen with someone over the internet.
You'll receive a 6-character code to share with the viewer.

Usage:
    python share_screen.py --relay ws://relay-server.com:8765
"""

import argparse
import asyncio
import logging
import sys

from relay.host_agent import RelayHostAgent, RelayHostConfig

# ---------------------------------------------------------------
# Default relay URL – change this when you deploy to EC2:
#   Local  : ws://127.0.0.1:8765
#   EC2    : ws://<EC2_PUBLIC_IP>:8765
# ---------------------------------------------------------------
DEFAULT_RELAY = "ws://13.204.132.109:8765"


def main():
    parser = argparse.ArgumentParser(
        description="Share your screen via relay server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Connect to local relay (for testing)
    python share_screen.py --relay ws://localhost:8765

    # Connect to remote relay server
    python share_screen.py --relay ws://your-server.com:8765

    # With custom quality settings
    python share_screen.py --relay ws://your-server.com:8765 --fps 24 --quality 60
"""
    )
    parser.add_argument("--relay", default=DEFAULT_RELAY,
                       help=f"Relay server URL (default: {DEFAULT_RELAY})")
    parser.add_argument("--fps", type=int, default=30,
                       help="Target frames per second (default: 30)")
    parser.add_argument("--quality", type=int, default=70,
                       help="JPEG quality 1-100 (default: 70)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    config = RelayHostConfig(
        relay_url=args.relay,
        capture_fps=args.fps,
        jpeg_quality=args.quality
    )
    
    print(f"\n⚙️  Performance Settings:")
    print(f"   FPS: {args.fps} (lower = less bandwidth)")
    print(f"   Quality: {args.quality}% (lower = faster encoding)")
    print(f"   Tip: Use --fps 15 --quality 50 for slower connections\n")

    agent = RelayHostAgent(config)

    async def run():
        if not await agent.connect_to_relay():
            print("\n❌ Failed to connect to relay server!")
            print(f"   Check that the relay is running at: {args.relay}")
            sys.exit(1)

        print(f"""
╔══════════════════════════════════════════════════════════════╗
║           🖥️  Screen Sharing Active                          ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   Your Session Code:                                         ║
║                                                              ║
║           ╔════════════════════════╗                         ║
║           ║   {agent.session_code:^18}   ║                         ║
║           ╚════════════════════════╝                         ║
║                                                              ║
║   Share this code with the person who wants to view          ║
║   your screen. They need to enter it in their viewer.        ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  Screen: {agent.capture.screen_info.width}x{agent.capture.screen_info.height}  |  FPS: {args.fps}  |  Quality: {args.quality}%{' ' * (21 - len(str(agent.capture.screen_info.width)) - len(str(agent.capture.screen_info.height)))}║
╠══════════════════════════════════════════════════════════════╣
║  ⏳ Waiting for viewer to connect...                         ║
║                                                              ║
║  Press Ctrl+C to stop sharing                                ║
╚══════════════════════════════════════════════════════════════╝
""")

        try:
            await agent.start()
        except KeyboardInterrupt:
            print("\n\n👋 Screen sharing stopped.")
        finally:
            await agent.stop()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")


if __name__ == "__main__":
    main()
