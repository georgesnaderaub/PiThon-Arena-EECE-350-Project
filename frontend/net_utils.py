"""Simple frontend network message helpers."""

import json


#encodes one message envelope as newline-delimited JSON bytes.
def encode_message(message_type, payload=None):
    envelope = {
        "type": message_type,
        "payload": payload or {},
    }
    return (json.dumps(envelope, separators=(",", ":")) + "\n").encode("utf-8")


#decodes one newline-delimited JSON message into a python dict.
def decode_message(line):
    data = json.loads(line.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Message must be an object")
    if not isinstance(data.get("type"), str) or not data.get("type"):
        raise ValueError("Message type is invalid")
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("Message payload must be an object")
    return {
        "type": data["type"],
        "payload": payload,
    }
