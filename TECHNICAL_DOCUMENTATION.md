# Remote Desktop - Technical Documentation

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Technology Stack](#technology-stack)
4. [Components](#components)
5. [Protocol Specification](#protocol-specification)
6. [File Structure](#file-structure)
7. [Setup & Installation](#setup--installation)
8. [Usage Guide](#usage-guide)
9. [Configuration](#configuration)
10. [Network Modes](#network-modes)
11. [Security Considerations](#security-considerations)
12. [Troubleshooting](#troubleshooting)

---

## Project Overview

**Remote Desktop** is a Python-based screen sharing and remote control application that enables users to view and control remote computers. The project supports two connection modes:

| Mode | Use Case | Requirements |
|------|----------|--------------|
| **Local Network (P2P)** | Same WiFi/LAN | Direct connection |
| **Internet (Relay)** | Anywhere in the world | Relay server on public cloud |

### Key Features

- Real-time screen capture and streaming (30+ FPS)
- Mouse and keyboard input forwarding
- Session-based connections with 6-character codes
- Cross-network connectivity via relay server
- Configurable quality and frame rate
- PyGame-based GUI viewer

---

## Architecture

### Local Network Mode (Direct P2P)

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  SIGNALING      │         │     HOST        │         │     CLIENT      │
│  SERVER         │         │  (Screen Share) │         │    (Viewer)     │
│  Port: 9000     │         │  Port: 9001     │         │                 │
└────────┬────────┘         └────────┬────────┘         └────────┬────────┘
         │                           │                           │
         │◄── 1. Register ───────────┤                           │
         │     (session_id, port)    │                           │
         │                           │                           │
         │◄────────────────────────── 2. Lookup ─────────────────┤
         │      (session_id)                                     │
         │                                                       │
         ├─── 3. Host Info ─────────────────────────────────────►│
         │     (IP, port)                                        │
         │                           │                           │
         │                           │◄── 4. Direct Connect ─────┤
         │                           │     (WebSocket)           │
         │                           │                           │
         │                           │◄══ 5. Stream Frames ═════►│
         │                           │◄══ 6. Send Input ════════►│
         │                           │                           │
```

### Internet Mode (Relay)

```
┌─────────────────┐                    ┌─────────────────┐
│     HOST        │                    │     CLIENT      │
│  (Screen Share) │                    │    (Viewer)     │
└────────┬────────┘                    └────────┬────────┘
         │                                      │
         │                                      │
         │    ┌─────────────────────────┐       │
         │    │      RELAY SERVER       │       │
         │    │  (Public Cloud Server)  │       │
         │    │      Port: 8765         │       │
         │    └───────────┬─────────────┘       │
         │                │                     │
         ├── 1. Register ─►│                     │
         │                │                     │
         │◄─ 2. Code ─────┤                     │
         │    "ABC123"    │                     │
         │                │                     │
         │    [ User shares code verbally ]     │
         │                │                     │
         │                │◄── 3. Join ─────────┤
         │                │    "ABC123"         │
         │                │                     │
         │◄═══════════════╪═════════════════════╡
         │    4. Frames relayed through server  │
         ╞═════════════════════════════════════►│
         │    5. Input relayed through server   │
         │                │                     │
```

---

## Technology Stack

### Core Technologies

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Language** | Python 3.12+ | Primary development language |
| **Async Framework** | asyncio | Non-blocking I/O operations |
| **WebSocket** | websockets library | Real-time bidirectional communication |
| **GUI** | PyGame | Cross-platform viewer window |
| **Image Processing** | NumPy, Pillow | Frame manipulation and encoding |
| **Screen Capture** | Quartz (macOS) | Native screen capture API |

### Libraries & Dependencies

```
websockets>=12.0      # WebSocket client/server
numpy>=1.24.0         # Array operations for frames
Pillow>=10.0.0        # JPEG encoding/decoding
pygame>=2.5.0         # GUI viewer
pyobjc-framework-Quartz  # macOS screen capture (host only)
```

### Platform Support

| Platform | Host (Share Screen) | Client (View Screen) | Relay Server |
|----------|---------------------|----------------------|--------------|
| macOS | ✅ Full support | ✅ Full support | ✅ Full support |
| Linux | ⚠️ PIL fallback | ✅ Full support | ✅ Full support |
| Windows | ⚠️ PIL fallback | ✅ Full support | ✅ Full support |

---

## Components

### 1. Signaling Server (`signaling/server.py`)

**Purpose:** Session registration and discovery for local network mode.

**Technology:**
- Raw TCP sockets via `asyncio.start_server()`
- Custom binary protocol
- In-memory session storage with TTL

**Key Classes:**
```python
class Session:
    session_id: str      # 6-char identifier
    host_ip: str         # Host's IP address
    host_port: int       # Host's listening port
    last_heartbeat: float

class SessionManager:
    async def register(host_ip, host_port) -> session_id
    async def lookup(session_id) -> Session
    async def heartbeat(session_id) -> bool

class SignalingServer:
    async def start() -> None
    async def stop() -> None
```

**Port:** 9000 (TCP)

---

### 2. Host Server (`host/server.py`)

**Purpose:** Captures screen and streams to connected clients.

**Technology:**
- WebSocket server via `websockets.serve()`
- Screen capture via Quartz APIs (macOS) or PIL (fallback)
- JPEG encoding for frame compression

**Key Classes:**
```python
class HostStreamingServer:
    capture: ScreenCapture      # Screen grabber
    encoder: FrameEncoder       # JPEG encoder

    async def start(host, port) -> None
    async def _stream_loop() -> None    # Capture & send frames
    async def _handle_input(msg) -> None  # Process client input
```

**Port:** 9001 (WebSocket)

---

### 3. Screen Capture (`host/capture.py`)

**Purpose:** High-performance screen capture.

**Technology:**
- **macOS:** Quartz `CGWindowListCreateImage()` API
- **Fallback:** PIL `ImageGrab.grab()`

**Key Classes:**
```python
@dataclass
class Frame:
    data: np.ndarray    # RGB array (H, W, 3)
    width: int
    height: int
    timestamp: float
    frame_number: int

class ScreenCapture:
    def grab() -> Frame           # Synchronous capture
    async def grab_async() -> Frame  # Async wrapper

class FrameRateLimiter:
    def wait() -> float           # Maintain target FPS
    async def wait_async() -> float
```

**Performance:** ~5-10ms per capture on modern hardware (100+ FPS capable)

---

### 4. Frame Encoder (`host/encoder.py`)

**Purpose:** Compress frames for network transmission.

**Technology:**
- JPEG encoding via PIL/Pillow
- Configurable quality (1-100)
- RGB to JPEG conversion

**Key Classes:**
```python
@dataclass
class EncodedFrame:
    data: bytes           # JPEG bytes
    width: int
    height: int
    original_size: int    # Uncompressed size
    compressed_size: int  # JPEG size
    compression_ratio: float

class FrameEncoder:
    quality: int = 70     # JPEG quality

    def encode(frame: Frame) -> EncodedFrame
```

**Typical Compression:** 10-20x reduction (1080p frame: ~6MB → 300-600KB)

---

### 5. Frame Decoder (`client/decoder.py`)

**Purpose:** Decompress received frames for display.

**Technology:**
- JPEG decoding via PIL/Pillow
- Conversion to NumPy array for PyGame

**Key Classes:**
```python
@dataclass
class DecodedFrame:
    data: np.ndarray      # RGB array
    width: int
    height: int
    frame_number: int
    decode_time: float

class FrameDecoder:
    def decode(jpeg_data: bytes) -> DecodedFrame

class FrameBuffer:
    max_size: int = 3     # Buffer recent frames
    def add(frame) -> None
    def get_latest() -> DecodedFrame
```

---

### 6. Client Connection (`client/connection.py`)

**Purpose:** WebSocket client for receiving frames and sending input.

**Technology:**
- WebSocket client via `websockets.connect()`
- Async message handling
- Input event serialization

**Key Classes:**
```python
class ClientConnection:
    decoder: FrameDecoder
    frame_buffer: FrameBuffer

    async def connect(host, port, name) -> bool
    async def start_receiving() -> None
    async def send_mouse_move(x, y) -> None
    async def send_key_down(key_code, modifiers) -> None
```

---

### 7. GUI Viewer (`client/viewer.py`)

**Purpose:** Display remote screen and capture local input.

**Technology:**
- PyGame for window and rendering
- NumPy array to PyGame surface conversion
- Event loop for input capture

**Key Classes:**
```python
class RemoteDesktopViewer:
    screen: pygame.Surface
    scale: float          # Display scaling

    async def connect() -> bool
    def on_frame(frame) -> None      # Process incoming frame
    def render() -> None             # Blit to screen
    async def handle_events() -> bool  # Capture input
```

---

### 8. Relay Server (`relay/server.py`)

**Purpose:** Enable connections across NAT/firewalls via traffic relay.

**Technology:**
- WebSocket server via `websockets.serve()`
- Session code generation
- Bidirectional message forwarding

**Key Classes:**
```python
@dataclass
class RelaySession:
    session_code: str                    # 6-char code
    host_ws: WebSocketServerProtocol     # Host connection
    client_ws: WebSocketServerProtocol   # Client connection
    bytes_relayed: int

class RelayServer:
    async def start() -> None
    async def _handle_host_register(ws) -> None
    async def _handle_client_join(ws) -> None
    async def _relay_loop_host(session) -> None
    async def _relay_loop_client(session) -> None
```

**Port:** 8765 (WebSocket)

---

### 9. Relay Host Agent (`relay/host_agent.py`)

**Purpose:** Host-side relay client that streams through relay server.

**Key Classes:**
```python
class RelayHostAgent:
    capture: ScreenCapture
    encoder: FrameEncoder
    session_code: str

    async def connect_to_relay() -> bool
    async def start() -> None
    async def _stream_loop() -> None
```

---

### 10. Relay Viewer (`relay/viewer.py`)

**Purpose:** Client-side relay viewer that receives frames through relay.

**Key Classes:**
```python
class RelayViewer:
    session_code: str
    decoder: FrameDecoder

    async def connect() -> bool
    async def receive_loop() -> None
    async def run() -> None
```

---

## Protocol Specification

### Message Header Format

All messages use a common header:

```
┌─────────────┬─────────────────┬──────────────────┐
│  Type (1B)  │  Timestamp (8B) │  Payload Len (4B)│
├─────────────┴─────────────────┴──────────────────┤
│                 Payload (variable)               │
└──────────────────────────────────────────────────┘

Total Header: 13 bytes
Format: !BQI (network byte order)
```

### Message Types

#### Signaling Messages (0x01 - 0x0F)

| Type | Code | Direction | Purpose |
|------|------|-----------|---------|
| REGISTER | 0x01 | Host → Server | Register session |
| REGISTER_ACK | 0x02 | Server → Host | Confirm registration |
| LOOKUP | 0x03 | Client → Server | Find host by code |
| LOOKUP_RESPONSE | 0x04 | Server → Client | Return host info |
| HEARTBEAT | 0x05 | Host → Server | Keep session alive |
| HEARTBEAT_ACK | 0x06 | Server → Host | Confirm heartbeat |

#### P2P Messages (0x10 - 0x1F)

| Type | Code | Direction | Purpose |
|------|------|-----------|---------|
| CONNECT | 0x10 | Client → Host | Request connection |
| CONNECT_ACK | 0x11 | Host → Client | Accept connection |
| DISCONNECT | 0x12 | Either | End session |

#### Data Messages (0x20 - 0x2F)

| Type | Code | Direction | Purpose |
|------|------|-----------|---------|
| FRAME | 0x20 | Host → Client | Screen frame |
| INPUT | 0x21 | Client → Host | Input event |

#### Error Messages (0xF0 - 0xFF)

| Type | Code | Direction | Purpose |
|------|------|-----------|---------|
| ERROR | 0xF0 | Any | Error response |

### Frame Message Format

```
┌──────────────────────────────────────────────────┐
│                 Header (13 bytes)                │
├─────────────┬─────────────┬──────────────────────┤
│ Width (2B)  │ Height (2B) │ Frame Number (4B)    │
├─────────────┴─────────────┴──────────────────────┤
│              JPEG Data (variable)                │
└──────────────────────────────────────────────────┘
```

### Input Message Format

```
┌──────────────────────────────────────────────────┐
│                 Header (13 bytes)                │
├──────────┬───────┬───────┬────────┬──────────────┤
│ Type(1B) │ X(2B) │ Y(2B) │ Btn(1B)│ KeyCode(2B)  │
├──────────┴───────┴───────┴────────┴──────────────┤
│ Modifiers(1B) │ ScrollDelta(2B)                  │
└──────────────────────────────────────────────────┘

Total: 24 bytes (13 header + 11 payload)
```

### Input Event Types

| Type | Code | Fields Used |
|------|------|-------------|
| MOUSE_MOVE | 0x01 | x, y |
| MOUSE_DOWN | 0x02 | x, y, button |
| MOUSE_UP | 0x03 | x, y, button |
| MOUSE_SCROLL | 0x04 | x, y, scroll_delta |
| KEY_DOWN | 0x05 | key_code, modifiers |
| KEY_UP | 0x06 | key_code, modifiers |

### Relay Protocol Messages

| Type | Code | Payload | Purpose |
|------|------|---------|---------|
| HOST_REGISTER | 0x01 | JSON | Register as host |
| HOST_REGISTERED | 0x02 | JSON {session_code} | Confirm with code |
| CLIENT_JOIN | 0x03 | JSON {session_code} | Join with code |
| CLIENT_JOINED | 0x04 | JSON | Confirm join |
| CLIENT_CONNECTED | 0x05 | JSON | Notify host |
| DISCONNECT | 0x10 | JSON {reason} | Disconnect |
| ERROR | 0x11 | JSON {error} | Error message |

---

## File Structure

```
Remote_Desktop/
├── common/                     # Shared code
│   ├── __init__.py
│   ├── config.py              # Configuration classes
│   └── protocol.py            # Message definitions
│
├── signaling/                  # Signaling server (local network)
│   ├── __init__.py
│   └── server.py              # TCP signaling server
│
├── host/                       # Host/screen share components
│   ├── __init__.py
│   ├── capture.py             # Screen capture (Quartz/PIL)
│   ├── encoder.py             # JPEG encoding
│   └── server.py              # WebSocket streaming server
│
├── client/                     # Client/viewer components
│   ├── __init__.py
│   ├── decoder.py             # JPEG decoding
│   ├── connection.py          # WebSocket client
│   └── viewer.py              # PyGame GUI viewer
│
├── relay/                      # Internet relay components
│   ├── __init__.py
│   ├── server.py              # WebSocket relay server
│   ├── host_agent.py          # Host relay client
│   └── viewer.py              # Viewer relay client
│
├── run_server.py              # Start signaling server
├── run_relay.py               # Start relay server
├── share_screen.py            # Share screen via relay
├── view_screen.py             # View screen via relay
│
├── test_signaling.py          # Signaling tests
├── test_pipeline.py           # Pipeline tests
└── test_network.py            # Network tests
```

---

## Setup & Installation

### Prerequisites

- Python 3.12 or higher
- pip (Python package manager)
- macOS (for native screen capture) or any OS (with PIL fallback)

### Installation

```bash
# Clone or navigate to project
cd Remote_Desktop

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # macOS/Linux
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install websockets numpy Pillow pygame

# For macOS host (native screen capture)
pip install pyobjc-framework-Quartz
```

### Verify Installation

```bash
# Test screen capture
python -c "from host.capture import ScreenCapture; s = ScreenCapture(); print(f'Screen: {s.screen_info.width}x{s.screen_info.height}')"

# Test imports
python -c "import websockets, numpy, pygame, PIL; print('All dependencies OK')"
```

---

## Usage Guide

### Mode 1: Local Network (Same WiFi/LAN)

**Terminal 1 - Start Signaling Server:**
```bash
python run_server.py --port 9000
```

**Terminal 2 - Start Host (machine to share):**
```bash
python host/server.py --host 0.0.0.0 --port 9001 --fps 30 --quality 70
```

**Terminal 3 - Start Viewer (machine to view):**
```bash
python client/viewer.py --host <HOST_IP> --port 9001 --scale 1.0
```

### Mode 2: Internet (Via Relay Server)

**Step 1 - Deploy Relay Server (on public cloud VPS):**
```bash
# On your cloud server (AWS, DigitalOcean, etc.)
python run_relay.py --host 0.0.0.0 --port 8765
```

**Step 2 - Share Screen (on machine to share):**
```bash
python share_screen.py --relay ws://your-server.com:8765

# Output:
#   Session Code: ABC123
#   Share this code with the viewer...
```

**Step 3 - View Screen (on any machine with the code):**
```bash
python view_screen.py --relay ws://your-server.com:8765 --code ABC123
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RD_SIGNALING_HOST` | 0.0.0.0 | Signaling server bind address |
| `RD_SIGNALING_PORT` | 9000 | Signaling server port |
| `RD_HOST_LISTEN_PORT` | 9001 | Host streaming port |
| `RD_HOST_FPS` | 30 | Target frames per second |
| `RD_HOST_JPEG_QUALITY` | 70 | JPEG quality (1-100) |
| `RD_LOG_LEVEL` | INFO | Logging level |

### Configuration Classes

```python
# common/config.py

@dataclass
class SignalingConfig:
    host: str = "0.0.0.0"
    port: int = 9000
    session_timeout: int = 60
    max_sessions: int = 100

@dataclass
class HostConfig:
    listen_port: int = 9001
    capture_fps: int = 30
    jpeg_quality: int = 70

@dataclass
class ClientConfig:
    window_width: int = 1280
    window_height: int = 720
    fullscreen: bool = False
```

---

## Network Modes

### Local Network Mode

| Aspect | Details |
|--------|---------|
| **Latency** | Very low (~1-5ms) |
| **Bandwidth** | LAN speed (1Gbps+) |
| **NAT/Firewall** | Must be on same network |
| **Setup** | Simple, no external server |

**When to use:** Same office, home network, or when low latency is critical.

### Relay Mode

| Aspect | Details |
|--------|---------|
| **Latency** | Higher (depends on server location) |
| **Bandwidth** | Limited by server + internet speed |
| **NAT/Firewall** | Works across any network |
| **Setup** | Requires public relay server |

**When to use:** Remote support, accessing home PC from anywhere, cross-network sharing.

### Relay Server Deployment Options

| Platform | Typical Cost | Setup Difficulty |
|----------|--------------|------------------|
| DigitalOcean Droplet | $6/month | Easy |
| AWS EC2 t3.micro | ~$8/month | Medium |
| Google Cloud e2-micro | Free tier | Medium |
| Linode Nanode | $5/month | Easy |
| Self-hosted (home server) | Free | Requires port forwarding |

---

## Security Considerations

### Current Security Model

| Aspect | Status | Notes |
|--------|--------|-------|
| Encryption | ❌ None | Traffic is unencrypted |
| Authentication | ❌ Basic | Session codes only |
| Authorization | ❌ None | Anyone with code can connect |

### Recommendations for Production

1. **Use WSS (WebSocket Secure)**
   ```python
   # Add TLS/SSL to relay server
   ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
   ssl_context.load_cert_chain('cert.pem', 'key.pem')
   ```

2. **Add Password Protection**
   ```python
   # Require password in addition to session code
   class RelaySession:
       password_hash: str
   ```

3. **Rate Limiting**
   ```python
   # Limit connection attempts per IP
   MAX_ATTEMPTS_PER_MINUTE = 10
   ```

4. **Session Expiration**
   ```python
   # Auto-expire sessions after timeout
   SESSION_TTL = 3600  # 1 hour
   ```

---

## Troubleshooting

### Common Issues

#### "Screen capture failed"
```bash
# macOS: Grant screen recording permission
System Preferences → Security & Privacy → Privacy → Screen Recording
# Add Terminal or your Python executable
```

#### "Connection refused"
```bash
# Check if server is running
lsof -i :9001  # Host port
lsof -i :8765  # Relay port

# Check firewall
sudo ufw status  # Linux
```

#### "Session not found"
- Session codes expire after 60 seconds without heartbeat
- Codes are case-insensitive but must be exactly 6 characters
- Host must be connected before client tries to join

#### "Low FPS / Laggy"
```bash
# Reduce quality for better performance
python share_screen.py --relay ws://... --fps 24 --quality 50

# Check bandwidth
# Typical requirements:
# - 720p @ 30fps: ~5-10 Mbps
# - 1080p @ 30fps: ~10-20 Mbps
# - 4K @ 30fps: ~40-80 Mbps
```

#### "Viewer window is black"
- Wait a few seconds for first frame
- Check that host has "Client connected" message
- Try with `--debug` flag for detailed logs

### Debug Mode

```bash
# Enable verbose logging
python share_screen.py --relay ws://... --debug
python view_screen.py --relay ws://... --code ABC123 --debug
python run_relay.py --debug
```

---

## Performance Metrics

### Typical Performance (1080p display)

| Metric | Value |
|--------|-------|
| Screen Capture | 5-10ms |
| JPEG Encode | 10-20ms |
| Network Transfer | 5-50ms (LAN) / 50-200ms (Internet) |
| JPEG Decode | 5-10ms |
| Display Render | 1-2ms |
| **Total Latency** | **30-100ms (LAN) / 80-300ms (Internet)** |

### Frame Size (JPEG Quality 70)

| Resolution | Typical Size | Bandwidth @ 30fps |
|------------|--------------|-------------------|
| 720p | 50-100 KB | 12-24 Mbps |
| 1080p | 100-200 KB | 24-48 Mbps |
| 1440p | 200-400 KB | 48-96 Mbps |
| 4K | 400-800 KB | 96-192 Mbps |

---

## Future Enhancements

- [ ] WebRTC for P2P through NAT (STUN/TURN)
- [ ] H.264/H.265 video encoding
- [ ] Audio streaming
- [ ] File transfer
- [ ] Clipboard sync
- [ ] Multi-monitor support
- [ ] Session recording
- [ ] Web-based viewer (no PyGame dependency)
- [ ] Mobile viewer apps
- [ ] End-to-end encryption

---

## License

This project is for educational purposes.

---

*Documentation generated: January 2026*
*Version: 2.0 (with Relay Support)*
