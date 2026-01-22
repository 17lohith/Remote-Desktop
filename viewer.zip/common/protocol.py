"""
Remote Desktop Protocol Definition

All message formats for signaling and P2P communication.
Uses struct for efficient binary serialization.
"""

import struct
import json
import time
import secrets
import string
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple, Any


# =============================================================================
# Message Types
# =============================================================================

class MessageType(IntEnum):
    # Signaling messages (0x01 - 0x0F)
    REGISTER = 0x01         # Host → Server: Register session
    REGISTER_ACK = 0x02     # Server → Host: Registration confirmed
    LOOKUP = 0x03           # Client → Server: Find host by session ID
    LOOKUP_RESPONSE = 0x04  # Server → Client: Host connection info
    HEARTBEAT = 0x05        # Host → Server: Keep session alive
    HEARTBEAT_ACK = 0x06    # Server → Host: Heartbeat confirmed

    # P2P connection messages (0x10 - 0x1F)
    CONNECT = 0x10          # Client → Host: Request connection
    CONNECT_ACK = 0x11      # Host → Client: Connection accepted
    DISCONNECT = 0x12       # Either → Either: End session

    # Data messages (0x20 - 0x2F)
    FRAME = 0x20            # Host → Client: Screen frame data
    INPUT = 0x21            # Client → Host: Input event

    # Error messages (0xF0 - 0xFF)
    ERROR = 0xF0            # Any: Error response


class InputEventType(IntEnum):
    MOUSE_MOVE = 0x01
    MOUSE_DOWN = 0x02
    MOUSE_UP = 0x03
    MOUSE_SCROLL = 0x04
    KEY_DOWN = 0x05
    KEY_UP = 0x06


class MouseButton(IntEnum):
    LEFT = 0
    RIGHT = 1
    MIDDLE = 2


class ErrorCode(IntEnum):
    SUCCESS = 0
    SESSION_NOT_FOUND = 1
    SESSION_EXPIRED = 2
    INVALID_MESSAGE = 3
    CONNECTION_REFUSED = 4
    PROTOCOL_ERROR = 5


# =============================================================================
# Header Format
# =============================================================================

# Common header: [type:1][timestamp:8][payload_length:4] = 13 bytes
HEADER_FORMAT = '!BQI'  # Network byte order: unsigned char, unsigned long long, unsigned int
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def pack_header(msg_type: MessageType, payload_length: int) -> bytes:
    """Pack message header."""
    timestamp = int(time.time() * 1000)  # Milliseconds
    return struct.pack(HEADER_FORMAT, msg_type, timestamp, payload_length)


def unpack_header(data: bytes) -> Tuple[MessageType, int, int]:
    """Unpack message header. Returns (type, timestamp, payload_length)."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Header too short: {len(data)} < {HEADER_SIZE}")
    msg_type, timestamp, payload_length = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    return MessageType(msg_type), timestamp, payload_length


# =============================================================================
# Session ID Generation
# =============================================================================

def generate_session_id(length: int = 6) -> str:
    """Generate a random session ID (alphanumeric, uppercase)."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def validate_session_id(session_id: str) -> bool:
    """Validate session ID format."""
    if not session_id or len(session_id) != 6:
        return False
    valid_chars = set(string.ascii_uppercase + string.digits)
    return all(c in valid_chars for c in session_id)


# =============================================================================
# Message Dataclasses
# =============================================================================

@dataclass
class RegisterMessage:
    """Host registration message."""
    session_id: str
    host_port: int  # Port host is listening on for P2P

    def pack(self) -> bytes:
        """Serialize to bytes."""
        payload = json.dumps({
            'session_id': self.session_id,
            'host_port': self.host_port
        }).encode('utf-8')
        return pack_header(MessageType.REGISTER, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'RegisterMessage':
        """Deserialize from bytes."""
        data = json.loads(payload.decode('utf-8'))
        return cls(session_id=data['session_id'], host_port=data['host_port'])


@dataclass
class RegisterAckMessage:
    """Registration acknowledgment."""
    success: bool
    session_id: str
    error_code: ErrorCode = ErrorCode.SUCCESS

    def pack(self) -> bytes:
        payload = json.dumps({
            'success': self.success,
            'session_id': self.session_id,
            'error_code': self.error_code
        }).encode('utf-8')
        return pack_header(MessageType.REGISTER_ACK, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'RegisterAckMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(
            success=data['success'],
            session_id=data['session_id'],
            error_code=ErrorCode(data['error_code'])
        )


@dataclass
class LookupMessage:
    """Client lookup request."""
    session_id: str

    def pack(self) -> bytes:
        payload = json.dumps({'session_id': self.session_id}).encode('utf-8')
        return pack_header(MessageType.LOOKUP, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'LookupMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(session_id=data['session_id'])


@dataclass
class LookupResponseMessage:
    """Server response with host info."""
    success: bool
    session_id: str
    host_ip: Optional[str] = None
    host_port: Optional[int] = None
    error_code: ErrorCode = ErrorCode.SUCCESS

    def pack(self) -> bytes:
        payload = json.dumps({
            'success': self.success,
            'session_id': self.session_id,
            'host_ip': self.host_ip,
            'host_port': self.host_port,
            'error_code': self.error_code
        }).encode('utf-8')
        return pack_header(MessageType.LOOKUP_RESPONSE, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'LookupResponseMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(
            success=data['success'],
            session_id=data['session_id'],
            host_ip=data.get('host_ip'),
            host_port=data.get('host_port'),
            error_code=ErrorCode(data['error_code'])
        )


@dataclass
class HeartbeatMessage:
    """Keep session alive."""
    session_id: str

    def pack(self) -> bytes:
        payload = json.dumps({'session_id': self.session_id}).encode('utf-8')
        return pack_header(MessageType.HEARTBEAT, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'HeartbeatMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(session_id=data['session_id'])


@dataclass
class HeartbeatAckMessage:
    """Heartbeat acknowledgment."""
    session_id: str

    def pack(self) -> bytes:
        payload = json.dumps({'session_id': self.session_id}).encode('utf-8')
        return pack_header(MessageType.HEARTBEAT_ACK, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'HeartbeatAckMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(session_id=data['session_id'])


@dataclass
class ConnectMessage:
    """P2P connection request."""
    session_id: str
    client_name: str = "Client"

    def pack(self) -> bytes:
        payload = json.dumps({
            'session_id': self.session_id,
            'client_name': self.client_name
        }).encode('utf-8')
        return pack_header(MessageType.CONNECT, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'ConnectMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(session_id=data['session_id'], client_name=data.get('client_name', 'Client'))


@dataclass
class ConnectAckMessage:
    """P2P connection acknowledgment."""
    success: bool
    screen_width: int = 0
    screen_height: int = 0

    def pack(self) -> bytes:
        payload = json.dumps({
            'success': self.success,
            'screen_width': self.screen_width,
            'screen_height': self.screen_height
        }).encode('utf-8')
        return pack_header(MessageType.CONNECT_ACK, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'ConnectAckMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(
            success=data['success'],
            screen_width=data.get('screen_width', 0),
            screen_height=data.get('screen_height', 0)
        )


@dataclass
class DisconnectMessage:
    """Session disconnect."""
    reason: str = "User disconnected"

    def pack(self) -> bytes:
        payload = json.dumps({'reason': self.reason}).encode('utf-8')
        return pack_header(MessageType.DISCONNECT, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'DisconnectMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(reason=data.get('reason', 'Unknown'))


@dataclass
class FrameMessage:
    """Screen frame data."""
    width: int
    height: int
    frame_data: bytes  # Compressed image data (JPEG)
    frame_number: int = 0

    def pack(self) -> bytes:
        # Frame header: width(2) + height(2) + frame_number(4) + data
        frame_header = struct.pack('!HHI', self.width, self.height, self.frame_number)
        payload = frame_header + self.frame_data
        return pack_header(MessageType.FRAME, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'FrameMessage':
        width, height, frame_number = struct.unpack('!HHI', payload[:8])
        frame_data = payload[8:]
        return cls(width=width, height=height, frame_data=frame_data, frame_number=frame_number)


@dataclass
class InputMessage:
    """Input event from client."""
    event_type: InputEventType
    x: int = 0
    y: int = 0
    button: MouseButton = MouseButton.LEFT
    key_code: int = 0
    modifiers: int = 0  # Shift=1, Ctrl=2, Alt=4, Meta=8
    scroll_delta: int = 0

    def pack(self) -> bytes:
        # Input format: event_type(1) + x(2) + y(2) + button(1) + key_code(2) + modifiers(1) + scroll_delta(2)
        payload = struct.pack('!BHHBHBH',
            self.event_type,
            self.x,
            self.y,
            self.button,
            self.key_code,
            self.modifiers,
            self.scroll_delta & 0xFFFF  # Ensure unsigned
        )
        return pack_header(MessageType.INPUT, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'InputMessage':
        event_type, x, y, button, key_code, modifiers, scroll_delta = struct.unpack('!BHHBHBH', payload)
        return cls(
            event_type=InputEventType(event_type),
            x=x,
            y=y,
            button=MouseButton(button),
            key_code=key_code,
            modifiers=modifiers,
            scroll_delta=scroll_delta
        )


@dataclass
class ErrorMessage:
    """Error response."""
    error_code: ErrorCode
    message: str

    def pack(self) -> bytes:
        payload = json.dumps({
            'error_code': self.error_code,
            'message': self.message
        }).encode('utf-8')
        return pack_header(MessageType.ERROR, len(payload)) + payload

    @classmethod
    def unpack(cls, payload: bytes) -> 'ErrorMessage':
        data = json.loads(payload.decode('utf-8'))
        return cls(error_code=ErrorCode(data['error_code']), message=data['message'])


# =============================================================================
# Message Parser
# =============================================================================

MESSAGE_CLASSES = {
    MessageType.REGISTER: RegisterMessage,
    MessageType.REGISTER_ACK: RegisterAckMessage,
    MessageType.LOOKUP: LookupMessage,
    MessageType.LOOKUP_RESPONSE: LookupResponseMessage,
    MessageType.HEARTBEAT: HeartbeatMessage,
    MessageType.HEARTBEAT_ACK: HeartbeatAckMessage,
    MessageType.CONNECT: ConnectMessage,
    MessageType.CONNECT_ACK: ConnectAckMessage,
    MessageType.DISCONNECT: DisconnectMessage,
    MessageType.FRAME: FrameMessage,
    MessageType.INPUT: InputMessage,
    MessageType.ERROR: ErrorMessage,
}


def parse_message(data: bytes) -> Tuple[Any, bytes]:
    """
    Parse a message from raw bytes.
    Returns (message_object, remaining_bytes).
    """
    if len(data) < HEADER_SIZE:
        raise ValueError("Incomplete header")

    msg_type, timestamp, payload_length = unpack_header(data)
    total_length = HEADER_SIZE + payload_length

    if len(data) < total_length:
        raise ValueError(f"Incomplete message: have {len(data)}, need {total_length}")

    payload = data[HEADER_SIZE:total_length]
    remaining = data[total_length:]

    if msg_type not in MESSAGE_CLASSES:
        raise ValueError(f"Unknown message type: {msg_type}")

    message = MESSAGE_CLASSES[msg_type].unpack(payload)
    return message, remaining


async def read_message(reader) -> Any:
    """
    Read a complete message from an asyncio StreamReader.
    """
    # Read header first
    header_data = await reader.readexactly(HEADER_SIZE)
    msg_type, timestamp, payload_length = unpack_header(header_data)

    # Read payload
    payload = await reader.readexactly(payload_length)

    if msg_type not in MESSAGE_CLASSES:
        raise ValueError(f"Unknown message type: {msg_type}")

    return MESSAGE_CLASSES[msg_type].unpack(payload)


async def write_message(writer, message) -> None:
    """
    Write a message to an asyncio StreamWriter.
    """
    data = message.pack()
    writer.write(data)
    await writer.drain()
