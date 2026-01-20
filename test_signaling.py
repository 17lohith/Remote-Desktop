#!/usr/bin/env python3
"""
Test script for the signaling server.

Tests:
1. Session registration
2. Session lookup
3. Heartbeat
4. Session expiration

Usage:
    # Start the server first:
    python run_server.py

    # Then run tests:
    python test_signaling.py
"""

import asyncio
import logging
import sys

from common.protocol import (
    RegisterMessage,
    RegisterAckMessage,
    LookupMessage,
    LookupResponseMessage,
    HeartbeatMessage,
    HeartbeatAckMessage,
    read_message,
    write_message,
    generate_session_id,
    ErrorCode,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def test_register(host: str = "localhost", port: int = 9000):
    """Test session registration."""
    logger.info("=== Test: Registration ===")

    reader, writer = await asyncio.open_connection(host, port)

    try:
        # Register a session
        session_id = generate_session_id()
        msg = RegisterMessage(session_id=session_id, host_port=9001)
        await write_message(writer, msg)
        logger.info(f"Sent register request for session: {session_id}")

        # Read response
        response = await read_message(reader)
        assert isinstance(response, RegisterAckMessage), f"Unexpected response: {type(response)}"
        assert response.success, f"Registration failed: {response.error_code}"
        logger.info(f"Registration successful! Session ID: {response.session_id}")

        return response.session_id

    finally:
        writer.close()
        await writer.wait_closed()


async def test_lookup(session_id: str, host: str = "localhost", port: int = 9000):
    """Test session lookup."""
    logger.info("=== Test: Lookup ===")

    reader, writer = await asyncio.open_connection(host, port)

    try:
        # Lookup the session
        msg = LookupMessage(session_id=session_id)
        await write_message(writer, msg)
        logger.info(f"Sent lookup request for session: {session_id}")

        # Read response
        response = await read_message(reader)
        assert isinstance(response, LookupResponseMessage), f"Unexpected response: {type(response)}"
        assert response.success, f"Lookup failed: {response.error_code}"
        logger.info(f"Lookup successful! Host: {response.host_ip}:{response.host_port}")

        return response

    finally:
        writer.close()
        await writer.wait_closed()


async def test_lookup_nonexistent(host: str = "localhost", port: int = 9000):
    """Test lookup of non-existent session."""
    logger.info("=== Test: Lookup Non-existent ===")

    reader, writer = await asyncio.open_connection(host, port)

    try:
        # Lookup a fake session
        msg = LookupMessage(session_id="XXXXXX")
        await write_message(writer, msg)
        logger.info("Sent lookup request for non-existent session")

        # Read response
        response = await read_message(reader)
        assert isinstance(response, LookupResponseMessage), f"Unexpected response: {type(response)}"
        assert not response.success, "Lookup should have failed"
        assert response.error_code == ErrorCode.SESSION_NOT_FOUND, f"Wrong error: {response.error_code}"
        logger.info(f"Correctly got SESSION_NOT_FOUND error")

    finally:
        writer.close()
        await writer.wait_closed()


async def test_heartbeat(session_id: str, host: str = "localhost", port: int = 9000):
    """Test heartbeat."""
    logger.info("=== Test: Heartbeat ===")

    reader, writer = await asyncio.open_connection(host, port)

    try:
        # Send heartbeat
        msg = HeartbeatMessage(session_id=session_id)
        await write_message(writer, msg)
        logger.info(f"Sent heartbeat for session: {session_id}")

        # Read response
        response = await read_message(reader)
        assert isinstance(response, HeartbeatAckMessage), f"Unexpected response: {type(response)}"
        logger.info("Heartbeat acknowledged")

    finally:
        writer.close()
        await writer.wait_closed()


async def test_multiple_sessions(host: str = "localhost", port: int = 9000):
    """Test multiple concurrent sessions."""
    logger.info("=== Test: Multiple Sessions ===")

    sessions = []
    for i in range(3):
        reader, writer = await asyncio.open_connection(host, port)
        try:
            msg = RegisterMessage(session_id=generate_session_id(), host_port=9001 + i)
            await write_message(writer, msg)

            response = await read_message(reader)
            assert isinstance(response, RegisterAckMessage)
            assert response.success
            sessions.append(response.session_id)
            logger.info(f"Registered session {i+1}: {response.session_id}")
        finally:
            writer.close()
            await writer.wait_closed()

    # Verify all sessions are accessible
    for sid in sessions:
        response = await test_lookup(sid, host, port)
        assert response.success

    logger.info(f"All {len(sessions)} sessions verified!")


async def run_all_tests(host: str = "localhost", port: int = 9000):
    """Run all tests."""
    print("""
╔══════════════════════════════════════════════════════════╗
║           Signaling Server Test Suite                    ║
╚══════════════════════════════════════════════════════════╝
""")

    try:
        # Test 1: Registration
        session_id = await test_register(host, port)
        print("✓ Registration test passed\n")

        # Test 2: Lookup
        await test_lookup(session_id, host, port)
        print("✓ Lookup test passed\n")

        # Test 3: Heartbeat
        await test_heartbeat(session_id, host, port)
        print("✓ Heartbeat test passed\n")

        # Test 4: Non-existent lookup
        await test_lookup_nonexistent(host, port)
        print("✓ Non-existent lookup test passed\n")

        # Test 5: Multiple sessions
        await test_multiple_sessions(host, port)
        print("✓ Multiple sessions test passed\n")

        print("""
╔══════════════════════════════════════════════════════════╗
║              All Tests Passed!                           ║
╚══════════════════════════════════════════════════════════╝
""")

    except ConnectionRefusedError:
        print("\n✗ ERROR: Could not connect to signaling server.")
        print("  Make sure the server is running: python run_server.py")
        sys.exit(1)
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test the signaling server")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=9000, help="Server port")
    args = parser.parse_args()

    asyncio.run(run_all_tests(args.host, args.port))
