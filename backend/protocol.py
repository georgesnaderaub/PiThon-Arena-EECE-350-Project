"""Networking protocol helpers for newline-delimited JSON messages."""

import json


class ProtocolError(Exception):
    pass


def encode_message(message_type, payload=None):
    envelope = {
        "type": message_type,
        "payload": payload or {},
    }
    return (json.dumps(envelope, separators=(",", ":")) + "\n").encode("utf-8")


def send_message(connection, message_type, payload=None):
    connection.sendall(encode_message(message_type, payload))


def decode_message(line):
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("Invalid JSON message") from error

    if not isinstance(message, dict):
        raise ProtocolError("Message must be a JSON object")

    message_type = message.get("type")
    payload = message.get("payload", {})

    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("Message 'type' must be a non-empty string")

    if not isinstance(payload, dict):
        raise ProtocolError("Message 'payload' must be an object")

    return {
        "type": message_type,
        "payload": payload,
    }
