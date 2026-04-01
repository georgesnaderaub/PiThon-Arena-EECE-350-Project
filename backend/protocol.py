"""Networking protocol helpers for newline-delimited JSON messages."""

import json

#custom exception for invalid protocol messages.
class ProtocolError(Exception):
    pass

#wraps data as JSON object {"type": ..., "payload": ...} and appends \n for framing.
def encode_message(message_type, payload=None):
    envelope = {
        "type": message_type,
        "payload": payload or {},
    }
    return (json.dumps(envelope, separators=(",", ":")) + "\n").encode("utf-8")

#helper that encodes then sends one message with sendall.
def send_message(connection, message_type, payload=None):
    connection.sendall(encode_message(message_type, payload))


#parses one raw JSON line, validates shape 
# (type must be non-empty string, payload must be object), 
#returns normalized dict.
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
