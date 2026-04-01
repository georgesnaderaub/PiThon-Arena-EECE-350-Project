"""Data containers for connection-layer state."""


def create_connection_state():
    return {
        "online_users": {},
        "waiting_players": [],
        "spectators": set(),
    }


def create_user_session(connection, address):
    return {
        "socket": connection,
        "address": address,
        "username": None,
        "role": "player",
        "read_buffer": b"",
    }
