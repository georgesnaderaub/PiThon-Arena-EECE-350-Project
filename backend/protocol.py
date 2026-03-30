"""Networking protocol utilities for newline-delimited JSON messages."""

from __future__ import annotations

import json
import socket
from typing import Any, Dict


class ProtocolError(Exception):
    """Raised when a protocol message is malformed."""


def encode_message(message_type: str, payload: Dict[str, Any] | None = None) -> bytes:
    """Encode a message envelope as newline-delimited JSON bytes."""
    envelope = {
        "type": message_type,
        "payload": payload or {},
    }
    return (json.dumps(envelope, separators=(",", ":")) + "\n").encode("utf-8")


def send_message(sock: socket.socket, message_type: str, payload: Dict[str, Any] | None = None) -> None:
    """Send one JSON envelope on the socket."""
    sock.sendall(encode_message(message_type, payload))


def decode_message(line: bytes) -> Dict[str, Any]:
    """Decode one newline-delimited JSON envelope and validate basic shape."""
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Invalid JSON message") from exc

    if not isinstance(message, dict):
        raise ProtocolError("Message must be a JSON object")

    message_type = message.get("type")
    payload = message.get("payload", {})

    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("Message 'type' must be a non-empty string")

    if not isinstance(payload, dict):
        raise ProtocolError("Message 'payload' must be an object")

    return {"type": message_type, "payload": payload}
