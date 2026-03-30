"""Data models for server connection and lobby state."""

from __future__ import annotations

from dataclasses import dataclass, field
import socket
from typing import Optional


@dataclass
class UserSession:
    """Represents one connected client session."""

    socket: socket.socket
    address: tuple[str, int]
    username: Optional[str] = None
    role: str = "player"  # player | spectator
    read_buffer: bytes = b""


@dataclass
class ConnectionState:
    """In-memory state for currently connected clients."""

    online_users: dict[str, UserSession] = field(default_factory=dict)
    waiting_players: list[str] = field(default_factory=list)
    spectators: set[str] = field(default_factory=set)
