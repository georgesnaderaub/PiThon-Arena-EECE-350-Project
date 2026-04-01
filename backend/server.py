"""Connection-layer server for ΠThon Arena."""

import argparse
import logging
import socket
import threading

from .models import create_connection_state, create_user_session
from .protocol import ProtocolError, decode_message, send_message


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
BUFFER_SIZE = 4096
SOCKET_TIMEOUT_SECONDS = 0.5

LOGGER = logging.getLogger("python_arena.server")
RUNNING = threading.Event()
STATE_LOCK = threading.Lock()
STATE = create_connection_state()


def snapshot_online_users():
    with STATE_LOCK:
        return sorted(STATE["online_users"].keys())


def broadcast_online_users():
    users = snapshot_online_users()

    with STATE_LOCK:
        sessions = list(STATE["online_users"].values())

    for session in sessions:
        try:
            send_message(session["socket"], "ONLINE_USERS", {"users": users})
        except OSError:
            # If this send fails, cleanup happens in that client's thread.
            continue


def set_waiting(username):
    with STATE_LOCK:
        if username not in STATE["waiting_players"]:
            STATE["waiting_players"].append(username)
        STATE["spectators"].discard(username)


def set_spectator(username):
    with STATE_LOCK:
        STATE["spectators"].add(username)
        if username in STATE["waiting_players"]:
            STATE["waiting_players"].remove(username)


def close_connection(connection):
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass

    try:
        connection.close()
    except OSError:
        pass


def disconnect_session(session):
    username = session["username"]

    with STATE_LOCK:
        if username is not None:
            STATE["online_users"].pop(username, None)
            if username in STATE["waiting_players"]:
                STATE["waiting_players"].remove(username)
            STATE["spectators"].discard(username)

    close_connection(session["socket"])

    if username is not None:
        LOGGER.info("User disconnected: %s", username)
        broadcast_online_users()


def handle_login(session, payload):
    requested = payload.get("username")
    if not isinstance(requested, str):
        send_message(session["socket"], "LOGIN_REJECT", {"reason": "Username must be a string"})
        return

    username = requested.strip()
    if not username:
        send_message(session["socket"], "LOGIN_REJECT", {"reason": "Username cannot be empty"})
        return

    with STATE_LOCK:
        if session["username"] is not None:
            send_message(session["socket"], "LOGIN_REJECT", {"reason": "Already logged in"})
            return

        if username in STATE["online_users"]:
            send_message(session["socket"], "LOGIN_REJECT", {"reason": "Username already in use"})
            return

        session["username"] = username
        STATE["online_users"][username] = session

    LOGGER.info("User logged in: %s (%s:%d)", username, session["address"][0], session["address"][1])
    send_message(session["socket"], "LOGIN_OK", {"username": username})
    broadcast_online_users()


def dispatch_message(session, message):
    message_type = message["type"]
    payload = message["payload"]

    if message_type == "LOGIN":
        handle_login(session, payload)
        return

    if session["username"] is None:
        send_message(session["socket"], "ERROR", {"reason": "Authenticate with LOGIN first"})
        return

    if message_type == "WAITING":
        set_waiting(session["username"])
        send_message(session["socket"], "WAITING", {"status": "queued"})
        return

    if message_type == "WATCH_MATCH":
        set_spectator(session["username"])
        send_message(session["socket"], "WATCH_MATCH", {"status": "subscribed"})
        return

    send_message(session["socket"], "ERROR", {"reason": f"Unsupported message type '{message_type}'"})


def read_line(session):
    # Read one newline-delimited JSON message.
    while RUNNING.is_set():
        if b"\n" in session["read_buffer"]:
            line, _, rest = session["read_buffer"].partition(b"\n")
            session["read_buffer"] = rest
            return line.strip()

        try:
            chunk = session["socket"].recv(BUFFER_SIZE)
        except socket.timeout:
            continue
        except OSError:
            return None

        if not chunk:
            return None

        session["read_buffer"] += chunk

    return None


def handle_client(connection, address):
    session = create_user_session(connection, address)
    LOGGER.info("Client connected from %s:%d", address[0], address[1])

    try:
        while RUNNING.is_set():
            line = read_line(session)
            if line is None:
                break
            if not line:
                continue

            try:
                message = decode_message(line)
            except ProtocolError as error:
                send_message(session["socket"], "ERROR", {"reason": str(error)})
                continue

            dispatch_message(session, message)
    except ConnectionResetError:
        LOGGER.info("Connection reset by peer %s:%d", address[0], address[1])
    finally:
        disconnect_session(session)


def reset_state():
    with STATE_LOCK:
        sessions = list(STATE["online_users"].values())
        STATE["online_users"].clear()
        STATE["waiting_players"].clear()
        STATE["spectators"].clear()

    for session in sessions:
        close_connection(session["socket"])


def run_server(host, port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen()

    LOGGER.info("Server listening on %s:%d", host, port)
    RUNNING.set()

    try:
        while RUNNING.is_set():
            try:
                connection, address = server.accept()
            except OSError:
                break

            connection.settimeout(SOCKET_TIMEOUT_SECONDS)
            thread = threading.Thread(target=handle_client, args=(connection, address), daemon=True)
            thread.start()
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested by keyboard interrupt")
    finally:
        RUNNING.clear()
        close_connection(server)
        reset_state()


def parse_args():
    parser = argparse.ArgumentParser(description="ΠThon Arena connection-layer server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
