"""Connection-layer server for ΠThon Arena."""

from __future__ import annotations

import argparse
import logging
import socket
import threading
from typing import Iterable

from .models import ConnectionState, UserSession
from .protocol import ProtocolError, decode_message, send_message


LOGGER = logging.getLogger("python_arena.server")


class GameServer:
    """TCP server handling client connections and lobby presence."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.state = ConnectionState()
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._server_socket: socket.socket | None = None

    def start(self) -> None:
        """Start accepting client connections until interrupted."""
        self._running.set()

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen()

        self._server_socket = server_socket

        LOGGER.info("Server listening on %s:%d", self.host, self.port)

        try:
            while self._running.is_set():
                client_sock, address = server_socket.accept()
                client_sock.settimeout(0.5)
                session = UserSession(socket=client_sock, address=address)
                threading.Thread(
                    target=self._handle_client,
                    args=(session,),
                    daemon=True,
                    name=f"client-{address[0]}:{address[1]}",
                ).start()
        except KeyboardInterrupt:
            LOGGER.info("Shutdown requested by keyboard interrupt")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop server and close all active sockets."""
        self._running.clear()

        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None

        with self._lock:
            sessions = list(self.state.online_users.values())
            self.state.online_users.clear()
            self.state.waiting_players.clear()
            self.state.spectators.clear()

        for session in sessions:
            self._close_session_socket(session)

    def _handle_client(self, session: UserSession) -> None:
        """Process messages from one client until disconnect."""
        LOGGER.info("Client connected from %s:%d", *session.address)

        try:
            while self._running.is_set():
                line = self._read_line(session)
                if line is None:
                    break
                if not line:
                    continue

                try:
                    message = decode_message(line)
                except ProtocolError as exc:
                    send_message(session.socket, "ERROR", {"reason": str(exc)})
                    continue

                self._dispatch_message(session, message)
        except ConnectionResetError:
            LOGGER.info("Connection reset by peer %s:%d", *session.address)
        except OSError as exc:
            LOGGER.info("Socket closed for %s:%d (%s)", session.address[0], session.address[1], exc)
        finally:
            self._disconnect_session(session)

    def _read_line(self, session: UserSession) -> bytes | None:
        """Read one newline-delimited message from a session."""
        while self._running.is_set():
            if b"\n" in session.read_buffer:
                line, _, rest = session.read_buffer.partition(b"\n")
                session.read_buffer = rest
                return line.strip()

            try:
                chunk = session.socket.recv(4096)
            except socket.timeout:
                continue

            if not chunk:
                return None

            session.read_buffer += chunk

        return None

    def _dispatch_message(self, session: UserSession, message: dict) -> None:
        message_type = message["type"]
        payload = message["payload"]

        if message_type == "LOGIN":
            self._handle_login(session, payload)
            return

        if session.username is None:
            send_message(session.socket, "ERROR", {"reason": "Authenticate with LOGIN first"})
            return

        if message_type == "WAITING":
            self._set_waiting(session.username)
            send_message(session.socket, "WAITING", {"status": "queued"})
            return

        if message_type == "WATCH_MATCH":
            self._set_spectator(session.username)
            send_message(session.socket, "WATCH_MATCH", {"status": "subscribed"})
            return

        send_message(session.socket, "ERROR", {"reason": f"Unsupported message type '{message_type}'"})

    def _handle_login(self, session: UserSession, payload: dict) -> None:
        requested = payload.get("username")
        if not isinstance(requested, str):
            send_message(session.socket, "LOGIN_REJECT", {"reason": "Username must be a string"})
            return

        username = requested.strip()
        if not username:
            send_message(session.socket, "LOGIN_REJECT", {"reason": "Username cannot be empty"})
            return

        with self._lock:
            if session.username is not None:
                send_message(session.socket, "LOGIN_REJECT", {"reason": "Already logged in"})
                return

            if username in self.state.online_users:
                send_message(session.socket, "LOGIN_REJECT", {"reason": "Username already in use"})
                return

            session.username = username
            self.state.online_users[username] = session

        LOGGER.info("User logged in: %s (%s:%d)", username, *session.address)
        send_message(session.socket, "LOGIN_OK", {"username": username})
        self._broadcast_online_users()

    def _set_waiting(self, username: str) -> None:
        with self._lock:
            if username not in self.state.waiting_players:
                self.state.waiting_players.append(username)
            self.state.spectators.discard(username)

    def _set_spectator(self, username: str) -> None:
        with self._lock:
            self.state.spectators.add(username)
            if username in self.state.waiting_players:
                self.state.waiting_players.remove(username)

    def _disconnect_session(self, session: UserSession) -> None:
        username = session.username

        with self._lock:
            if username is not None:
                self.state.online_users.pop(username, None)
                if username in self.state.waiting_players:
                    self.state.waiting_players.remove(username)
                self.state.spectators.discard(username)

        self._close_session_socket(session)

        if username is not None:
            LOGGER.info("User disconnected: %s", username)
            self._broadcast_online_users()

    def _close_session_socket(self, session: UserSession) -> None:
        try:
            session.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            session.socket.close()
        except OSError:
            pass

    def _snapshot_online_users(self) -> Iterable[str]:
        with self._lock:
            return sorted(self.state.online_users.keys())

    def _broadcast_online_users(self) -> None:
        users = list(self._snapshot_online_users())

        with self._lock:
            sessions = list(self.state.online_users.values())

        for session in sessions:
            try:
                send_message(session.socket, "ONLINE_USERS", {"users": users})
            except OSError:
                # Connection is unhealthy; cleanup will happen by handler thread.
                continue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ΠThon Arena connection-layer server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=5000, help="Bind port")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    server = GameServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
