"""Backend server with lobby, matchmaking, and authoritative game loop."""

import argparse
import logging
import socket
import threading
import time

from .models import create_connection_state, create_match, create_user_session, spawn_pie
from .protocol import ProtocolError, decode_message, send_message


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
BUFFER_SIZE = 4096
SOCKET_TIMEOUT_SECONDS = 0.5

GRID_WIDTH = 30
GRID_HEIGHT = 20
TICK_RATE = 8
MATCH_DURATION_SECONDS = 60
STARTING_HEALTH = 100
PIE_HEAL = 10
WALL_DAMAGE = 15
OBSTACLE_DAMAGE = 10
SELF_DAMAGE = 20
ENEMY_DAMAGE = 20
HEAD_ON_DAMAGE = 20
COLLISION_PAUSE_SECONDS = 1

DIRECTION_DELTAS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}

OPPOSITE_DIRECTIONS = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
}

LOGGER = logging.getLogger("python_arena.server")
RUNNING = threading.Event()
STATE_LOCK = threading.Lock()
STATE = create_connection_state()


#returns the gameplay configuration used by each match.
def get_match_config():
    return {
        "grid_width": GRID_WIDTH,
        "grid_height": GRID_HEIGHT,
        "tick_rate": TICK_RATE,
        "duration_seconds": MATCH_DURATION_SECONDS,
        "starting_health": STARTING_HEALTH,
        "pie_heal": PIE_HEAL,
        "wall_damage": WALL_DAMAGE,
        "obstacle_damage": OBSTACLE_DAMAGE,
        "self_damage": SELF_DAMAGE,
        "enemy_damage": ENEMY_DAMAGE,
        "head_on_damage": HEAD_ON_DAMAGE,
        "collision_pause_ticks": COLLISION_PAUSE_SECONDS * TICK_RATE,
    }


#returns a thread-safe sorted list of online usernames.
def snapshot_online_users():
    with STATE_LOCK:
        return sorted(STATE["online_users"].keys())


#returns one serializable position object from a grid tuple.
def serialize_pos(position):
    return {
        "x": position[0],
        "y": position[1],
    }


#returns a serializable snake object for network messages.
def serialize_snake(snake):
    return {
        "body": [serialize_pos(pos) for pos in snake["body"]],
        "direction": snake["direction"],
        "health": snake["health"],
        "stun_ticks_remaining": snake.get("stun_ticks_remaining", 0),
    }


#builds a serializable snapshot payload for match state broadcasts.
def build_match_state_payload(match):
    return {
        "id": match["id"],
        "status": match["status"],
        "players": list(match["players"]),
        "tick": match["tick"],
        "remaining_ticks": match["remaining_ticks"],
        "remaining_seconds": round(match["remaining_ticks"] / TICK_RATE, 2),
        "winner": match["winner"],
        "reason": match["reason"],
        "snakes": {name: serialize_snake(snake) for name, snake in match["snakes"].items()},
        "obstacles": [serialize_pos(pos) for pos in match["obstacles"]],
        "pies": list(match["pies"]),
    }


#returns unique recipients for match broadcasts with players prioritized over spectators.
def get_match_recipients(match):
    with STATE_LOCK:
        names = list(match["players"]) + [name for name in STATE["spectators"] if name in STATE["online_users"]]
    return list(dict.fromkeys(names))


#sends one message to all currently connected users in the list.
def send_to_users(usernames, message_type, payload):
    with STATE_LOCK:
        sessions = [STATE["online_users"][name] for name in usernames if name in STATE["online_users"]]

    for session in sessions:
        try:
            send_message(session["socket"], message_type, payload)
        except OSError:
            continue


#sends ONLINE_USERS updates to all currently connected logged-in users.
def broadcast_online_users():
    users = snapshot_online_users()

    with STATE_LOCK:
        sessions = list(STATE["online_users"].values())

    for session in sessions:
        try:
            send_message(session["socket"], "ONLINE_USERS", {"users": users})
        except OSError:
            continue


#adds one username to waiting queue and removes spectator role for it.
def set_waiting(username):
    with STATE_LOCK:
        if username not in STATE["waiting_players"]:
            STATE["waiting_players"].append(username)
        STATE["spectators"].discard(username)


#adds one username to spectators and removes that user from waiting queue.
def set_spectator(username):
    with STATE_LOCK:
        STATE["spectators"].add(username)
        if username in STATE["waiting_players"]:
            STATE["waiting_players"].remove(username)


#removes all incoming and outgoing pending challenges for one username.
def clear_challenges_for(username):
    with STATE_LOCK:
        STATE["pending_challenges"].pop(username, None)
        to_delete = [target for target, challenger in STATE["pending_challenges"].items() if challenger == username]
        for target in to_delete:
            STATE["pending_challenges"].pop(target, None)


#returns a tuple of next head position after moving one step in direction.
def get_next_position(position, direction):
    dx, dy = DIRECTION_DELTAS[direction]
    return (position[0] + dx, position[1] + dy)


#returns true when requested direction is a direct reverse of current direction.
def is_reverse_direction(current_direction, requested_direction):
    return OPPOSITE_DIRECTIONS[current_direction] == requested_direction


#applies pending directions for each snake while blocking illegal reverse turns.
def apply_pending_directions(match):
    for snake in match["snakes"].values():
        if snake.get("stun_ticks_remaining", 0) > 0:
            continue
        requested = snake["pending_direction"]
        if not is_reverse_direction(snake["direction"], requested):
            snake["direction"] = requested


#moves each active snake forward by one cell and keeps its length unchanged.
def move_snakes(match):
    previous_bodies = {}
    for snake in match["snakes"].values():
        previous_bodies[id(snake)] = list(snake["body"])
        if snake.get("stun_ticks_remaining", 0) > 0:
            continue
        current_head = snake["body"][0]
        new_head = get_next_position(current_head, snake["direction"])
        snake["body"].insert(0, new_head)
        snake["body"].pop()
    return previous_bodies


#applies pie pickup effects and respawns a new pie when one is collected.
def apply_pie_logic(match, config):
    if not match["pies"]:
        spawn_pie(match, config)

    if not match["pies"]:
        return

    pie = match["pies"][0]
    pie_pos = (pie["x"], pie["y"])

    for snake in match["snakes"].values():
        if snake.get("stun_ticks_remaining", 0) > 0:
            continue
        if snake["body"][0] == pie_pos:
            snake["health"] = min(config["starting_health"], snake["health"] + pie["value"])
            spawn_pie(match, config)
            return


#returns collision damage totals and collided usernames for the current tick.
def evaluate_collisions(match, config):
    players = match["players"]
    one = players[0]
    two = players[1]
    snake_one = match["snakes"][one]
    snake_two = match["snakes"][two]

    width = config["grid_width"]
    height = config["grid_height"]
    obstacles = set(match["obstacles"])
    collided = set()
    damage = {one: 0, two: 0}

    for username, snake, other in ((one, snake_one, snake_two), (two, snake_two, snake_one)):
        if snake.get("stun_ticks_remaining", 0) > 0:
            continue

        head = snake["body"][0]

        if head[0] < 0 or head[0] >= width or head[1] < 0 or head[1] >= height:
            damage[username] += config["wall_damage"]
            collided.add(username)

        if head in obstacles:
            damage[username] += config["obstacle_damage"]
            collided.add(username)

        if head in snake["body"][1:]:
            damage[username] += config["self_damage"]
            collided.add(username)

        if head in other["body"]:
            damage[username] += config["enemy_damage"]
            collided.add(username)

    if snake_one["body"][0] == snake_two["body"][0]:
        if snake_one.get("stun_ticks_remaining", 0) == 0:
            damage[one] += config["head_on_damage"]
            collided.add(one)
        if snake_two.get("stun_ticks_remaining", 0) == 0:
            damage[two] += config["head_on_damage"]
            collided.add(two)

    return damage, collided


#applies collision damage to snake health values.
def apply_collision_damage(match, damage):
    for username, amount in damage.items():
        if amount <= 0:
            continue
        snake = match["snakes"][username]
        snake["health"] = max(0, snake["health"] - amount)


#returns one fallback turn direction for collision recovery.
def get_recovery_direction(snake):
    turn_order = {
        "UP": ["LEFT", "RIGHT", "DOWN", "UP"],
        "DOWN": ["RIGHT", "LEFT", "UP", "DOWN"],
        "LEFT": ["DOWN", "UP", "RIGHT", "LEFT"],
        "RIGHT": ["UP", "DOWN", "LEFT", "RIGHT"],
    }
    return turn_order[snake["direction"]][0]


#applies collision recovery by rolling back movement and starting pause/flicker state.
def apply_collision_recovery(match, config, previous_bodies, collided_usernames):
    if not collided_usernames:
        return

    pause_ticks = config["collision_pause_ticks"]
    for username in collided_usernames:
        snake = match["snakes"][username]
        snake["body"] = list(previous_bodies[id(snake)])
        snake["stun_ticks_remaining"] = pause_ticks
        snake["resume_direction"] = get_recovery_direction(snake)


#decrements collision pause counters and applies queued recovery direction when ready.
def advance_collision_timers(match):
    for snake in match["snakes"].values():
        if snake.get("stun_ticks_remaining", 0) <= 0:
            continue
        snake["stun_ticks_remaining"] = max(0, snake["stun_ticks_remaining"] - 1)
        if snake["stun_ticks_remaining"] == 0 and snake.get("resume_direction") is not None:
            snake["direction"] = snake["resume_direction"]
            snake["pending_direction"] = snake["resume_direction"]
            snake["resume_direction"] = None


#marks match as ended and sets winner and reason based on health and timer conditions.
def resolve_match_outcome(match):
    players = match["players"]
    one = players[0]
    two = players[1]
    health_one = match["snakes"][one]["health"]
    health_two = match["snakes"][two]["health"]

    if health_one <= 0 and health_two <= 0:
        match["status"] = "ended"
        match["winner"] = None
        match["reason"] = "both_eliminated"
        return

    if health_one <= 0:
        match["status"] = "ended"
        match["winner"] = two
        match["reason"] = "health_zero"
        return

    if health_two <= 0:
        match["status"] = "ended"
        match["winner"] = one
        match["reason"] = "health_zero"
        return

    if match["remaining_ticks"] <= 0:
        match["status"] = "ended"
        if health_one > health_two:
            match["winner"] = one
        elif health_two > health_one:
            match["winner"] = two
        else:
            match["winner"] = None
        match["reason"] = "timer_end"


#runs one authoritative game tick update over movement, items, collisions, and winner logic.
def advance_match_one_tick(match, config):
    match["tick"] += 1
    match["remaining_ticks"] = max(0, match["remaining_ticks"] - 1)

    advance_collision_timers(match)
    apply_pending_directions(match)
    previous_bodies = move_snakes(match)
    apply_pie_logic(match, config)
    collision_damage, collided_usernames = evaluate_collisions(match, config)
    apply_collision_damage(match, collision_damage)
    apply_collision_recovery(match, config, previous_bodies, collided_usernames)
    resolve_match_outcome(match)


#sends MATCH_START to both players and all spectators for the current active match.
def broadcast_match_start(match):
    state_payload = build_match_state_payload(match)
    players = list(match["players"])

    for username in players:
        opponent = players[1] if username == players[0] else players[0]
        send_to_users(
            [username],
            "MATCH_START",
            {
                "you": username,
                "opponent": opponent,
                "spectator": False,
                "match": state_payload,
            },
        )

    with STATE_LOCK:
        watcher_names = [
            name for name in STATE["spectators"]
            if name in STATE["online_users"] and name not in players
        ]

    for watcher in watcher_names:
        send_to_users(
            [watcher],
            "MATCH_START",
            {
                "you": watcher,
                "opponent": None,
                "spectator": True,
                "match": state_payload,
            },
        )


#broadcasts one STATE_UPDATE snapshot to active players and spectators.
def broadcast_state_update(match):
    payload = {
        "match": build_match_state_payload(match),
    }

    send_to_users(get_match_recipients(match), "STATE_UPDATE", payload)


#broadcasts GAME_OVER for one finished match.
def broadcast_game_over(match):
    payload = {
        "winner": match["winner"],
        "reason": match["reason"],
        "match": build_match_state_payload(match),
    }

    send_to_users(get_match_recipients(match), "GAME_OVER", payload)


#runs the match loop thread until the match ends or the server shuts down.
def run_match_loop(match_id):
    config = get_match_config()
    tick_sleep = 1.0 / config["tick_rate"]

    while RUNNING.is_set():
        time.sleep(tick_sleep)

        with STATE_LOCK:
            match = STATE["active_match"]
            if match is None or match["id"] != match_id:
                break

            if match["status"] == "running":
                advance_match_one_tick(match, config)

            snapshot = build_match_state_payload(match)
            ended = match["status"] == "ended"

        send_state = {"match": snapshot}

        recipients = get_match_recipients(match)

        send_to_users(recipients, "STATE_UPDATE", send_state)

        if ended:
            game_over_payload = {
                "winner": snapshot["winner"],
                "reason": snapshot["reason"],
                "match": snapshot,
            }
            send_to_users(recipients, "GAME_OVER", game_over_payload)

            with STATE_LOCK:
                if STATE["active_match"] is not None and STATE["active_match"]["id"] == match_id:
                    STATE["active_match"] = None
            break


#creates a new match if possible and starts its game loop thread.
def create_and_start_match(player_one, player_two):
    with STATE_LOCK:
        if STATE["active_match"] is not None:
            return None, "A match is already running"

        if player_one not in STATE["online_users"] or player_two not in STATE["online_users"]:
            return None, "Both players must be online"

        match_id = STATE["next_match_id"]
        STATE["next_match_id"] += 1
        match = create_match(match_id, player_one, player_two, get_match_config())
        STATE["active_match"] = match

        if player_one in STATE["waiting_players"]:
            STATE["waiting_players"].remove(player_one)
        if player_two in STATE["waiting_players"]:
            STATE["waiting_players"].remove(player_two)
        STATE["spectators"].discard(player_one)
        STATE["spectators"].discard(player_two)

        STATE["pending_challenges"].pop(player_one, None)
        STATE["pending_challenges"].pop(player_two, None)

        to_delete = [target for target, challenger in STATE["pending_challenges"].items() if challenger in (player_one, player_two)]
        for target in to_delete:
            STATE["pending_challenges"].pop(target, None)

    broadcast_match_start(match)

    thread = threading.Thread(target=run_match_loop, args=(match["id"],), daemon=True, name=f"match-{match['id']}")
    thread.start()

    return match, None


#safely closes a socket connection.
def close_connection(connection):
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass

    try:
        connection.close()
    except OSError:
        pass


#disconnects a session and updates online state, challenges, and match status.
def disconnect_session(session):
    username = session["username"]

    with STATE_LOCK:
        if username is not None:
            STATE["online_users"].pop(username, None)
            if username in STATE["waiting_players"]:
                STATE["waiting_players"].remove(username)
            STATE["spectators"].discard(username)
            STATE["pending_challenges"].pop(username, None)

            to_delete = [target for target, challenger in STATE["pending_challenges"].items() if challenger == username]
            for target in to_delete:
                STATE["pending_challenges"].pop(target, None)

            active_match = STATE["active_match"]
            if active_match is not None and username in active_match["players"] and active_match["status"] == "running":
                other = active_match["players"][0] if active_match["players"][1] == username else active_match["players"][1]
                active_match["status"] = "ended"
                active_match["winner"] = other if other in STATE["online_users"] else None
                active_match["reason"] = "player_disconnected"

    close_connection(session["socket"])

    if username is not None:
        LOGGER.info("User disconnected: %s", username)
        broadcast_online_users()


#handles login validation, uniqueness check, and LOGIN_OK response.
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


#handles a challenge request from one player to another player.
def handle_challenge_player(session, payload):
    challenger = session["username"]
    target = payload.get("target")

    if not isinstance(target, str) or not target.strip():
        send_message(session["socket"], "ERROR", {"reason": "target is required"})
        return

    target = target.strip()
    if target == challenger:
        send_message(session["socket"], "ERROR", {"reason": "Cannot challenge yourself"})
        return

    with STATE_LOCK:
        if STATE["active_match"] is not None:
            send_message(session["socket"], "ERROR", {"reason": "A match is already running"})
            return

        if target not in STATE["online_users"]:
            send_message(session["socket"], "ERROR", {"reason": "Target user is offline"})
            return

        if target in STATE["pending_challenges"]:
            send_message(session["socket"], "ERROR", {"reason": "Target already has a pending challenge"})
            return

        STATE["pending_challenges"][target] = challenger

    send_message(session["socket"], "CHALLENGE_PLAYER", {"status": "sent", "target": target})
    send_to_users([target], "CHALLENGE_RECEIVED", {"from": challenger})


#handles challenge acceptance and starts match creation when valid.
def handle_challenge_accept(session, payload):
    target_user = session["username"]
    challenger = payload.get("from")

    if not isinstance(challenger, str) or not challenger.strip():
        send_message(session["socket"], "ERROR", {"reason": "from is required"})
        return

    challenger = challenger.strip()

    with STATE_LOCK:
        pending_from = STATE["pending_challenges"].get(target_user)
        if pending_from != challenger:
            send_message(session["socket"], "ERROR", {"reason": "No matching pending challenge"})
            return

        STATE["pending_challenges"].pop(target_user, None)

    match, error = create_and_start_match(challenger, target_user)
    if error is not None:
        send_message(session["socket"], "ERROR", {"reason": error})
        return

    LOGGER.info("Match %s started: %s vs %s", match["id"], challenger, target_user)


#handles player directional input for the active match.
def handle_input(session, payload):
    username = session["username"]
    direction = payload.get("direction")

    if not isinstance(direction, str):
        send_message(session["socket"], "ERROR", {"reason": "direction must be a string"})
        return

    direction = direction.strip().upper()
    if direction not in DIRECTION_DELTAS:
        send_message(session["socket"], "ERROR", {"reason": "direction must be UP, DOWN, LEFT, or RIGHT"})
        return

    with STATE_LOCK:
        match = STATE["active_match"]
        if match is None or match["status"] != "running":
            send_message(session["socket"], "ERROR", {"reason": "No active running match"})
            return

        if username not in match["players"]:
            send_message(session["socket"], "ERROR", {"reason": "Only active players can send INPUT"})
            return

        match["snakes"][username]["pending_direction"] = direction


#handles spectator request and returns current match snapshot when available.
def handle_watch_match(session):
    username = session["username"]
    set_spectator(username)
    send_message(session["socket"], "WATCH_MATCH", {"status": "subscribed"})

    with STATE_LOCK:
        match = STATE["active_match"]
        if match is None:
            return
        payload = {
            "you": username,
            "opponent": None,
            "spectator": True,
            "match": build_match_state_payload(match),
        }

    send_message(session["socket"], "MATCH_START", payload)


#routes each message type to its backend handler.
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
        handle_watch_match(session)
        return

    if message_type == "CHALLENGE_PLAYER":
        handle_challenge_player(session, payload)
        return

    if message_type == "CHALLENGE_ACCEPT":
        handle_challenge_accept(session, payload)
        return

    if message_type == "INPUT":
        handle_input(session, payload)
        return

    send_message(session["socket"], "ERROR", {"reason": f"Unsupported message type '{message_type}'"})


#reads one newline-delimited message from a session.
def read_line(session):
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


#handles one client connection loop until disconnect.
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


#resets shared server state and closes all connected client sockets.
def reset_state():
    with STATE_LOCK:
        sessions = list(STATE["online_users"].values())
        STATE["online_users"].clear()
        STATE["waiting_players"].clear()
        STATE["spectators"].clear()
        STATE["pending_challenges"].clear()
        STATE["active_match"] = None

    for session in sessions:
        close_connection(session["socket"])


#runs the TCP accept loop and starts one handler thread for each new client.
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


#parses command line options for host, port, and logging level.
def parse_args():
    parser = argparse.ArgumentParser(description="ΠThon Arena backend server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    return parser.parse_args()


#configures logging and starts the server process.
def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
