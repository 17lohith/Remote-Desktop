"""
Remote Desktop Configuration

Centralized configuration for all components.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SignalingConfig:
    """Signaling server configuration."""
    host: str = "0.0.0.0"
    port: int = 9000
    session_timeout: int = 60  # Seconds before session expires without heartbeat
    max_sessions: int = 100    # Maximum concurrent sessions
    heartbeat_interval: int = 30  # How often host should send heartbeat


@dataclass
class HostConfig:
    """Host agent configuration."""
    # Signaling server
    signaling_host: str = "localhost"
    signaling_port: int = 9000

    # P2P listening
    listen_host: str = "0.0.0.0"
    listen_port: int = 9001  # Port for P2P connections

    # Screen capture
    capture_fps: int = 30
    jpeg_quality: int = 70  # 1-100, higher = better quality, larger size

    # Heartbeat
    heartbeat_interval: int = 30

    # Buffer sizes
    send_buffer_size: int = 65536


@dataclass
class ClientConfig:
    """Client viewer configuration."""
    # Signaling server
    signaling_host: str = "localhost"
    signaling_port: int = 9000

    # Display
    window_title: str = "Remote Desktop Viewer"
    window_width: int = 1280
    window_height: int = 720
    fullscreen: bool = False

    # Input
    input_send_rate: int = 60  # Max input events per second

    # Buffer sizes
    recv_buffer_size: int = 65536


@dataclass
class Config:
    """Master configuration."""
    signaling: SignalingConfig = field(default_factory=SignalingConfig)
    host: HostConfig = field(default_factory=HostConfig)
    client: ClientConfig = field(default_factory=ClientConfig)

    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


# Global default config
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config


def load_config_from_env() -> Config:
    """Load configuration from environment variables."""
    config = Config()

    # Signaling overrides
    if os.environ.get('RD_SIGNALING_HOST'):
        config.signaling.host = os.environ['RD_SIGNALING_HOST']
    if os.environ.get('RD_SIGNALING_PORT'):
        config.signaling.port = int(os.environ['RD_SIGNALING_PORT'])

    # Host overrides
    if os.environ.get('RD_HOST_SIGNALING_HOST'):
        config.host.signaling_host = os.environ['RD_HOST_SIGNALING_HOST']
    if os.environ.get('RD_HOST_SIGNALING_PORT'):
        config.host.signaling_port = int(os.environ['RD_HOST_SIGNALING_PORT'])
    if os.environ.get('RD_HOST_LISTEN_PORT'):
        config.host.listen_port = int(os.environ['RD_HOST_LISTEN_PORT'])
    if os.environ.get('RD_HOST_FPS'):
        config.host.capture_fps = int(os.environ['RD_HOST_FPS'])
    if os.environ.get('RD_HOST_JPEG_QUALITY'):
        config.host.jpeg_quality = int(os.environ['RD_HOST_JPEG_QUALITY'])

    # Client overrides
    if os.environ.get('RD_CLIENT_SIGNALING_HOST'):
        config.client.signaling_host = os.environ['RD_CLIENT_SIGNALING_HOST']
    if os.environ.get('RD_CLIENT_SIGNALING_PORT'):
        config.client.signaling_port = int(os.environ['RD_CLIENT_SIGNALING_PORT'])

    # Logging
    if os.environ.get('RD_LOG_LEVEL'):
        config.log_level = os.environ['RD_LOG_LEVEL']

    return config
