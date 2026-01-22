"""
Relay module for Remote Desktop over the internet.

This module enables connections across NAT/firewalls by relaying
all traffic through a central server.
"""

from .server import RelayServer

__all__ = ['RelayServer']
