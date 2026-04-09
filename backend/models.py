"""Data containers for backend server state."""

import random


#returns the global in-memory state dict used by the backend.
def create_connection_state():
    return {
        "online_users": {},
        "waiting_players": [],
        "spectators": set(),
        "pending_challenges": {},
        "active_match": None,
        "next_match_id": 1,
    }


#creates a per-client session dict with socket, address, username and read buffer.
def create_user_session(connection, address):
    return {
        "socket": connection,
        "address": address,
        "username": None,
        "role": "player",
        "read_buffer": b"",
    }


#creates a fresh match object with players, snakes, obstacles, and one starting pie.
def create_match(match_id, player_one, player_two, config):
    width = config["grid_width"]
    height = config["grid_height"]

    snake_one = {
        "body": [(2, height // 2), (1, height // 2), (0, height // 2)],
        "direction": "RIGHT",
        "pending_direction": "RIGHT",
        "health": config["starting_health"],
        "score": 0,
        "grow_pending": 0,
        "move_interval_ticks": 1,
        "move_tick_counter": 0,
        "slow_ticks_remaining": 0,
        "stun_ticks_remaining": 0,
        "resume_direction": None,
    }

    snake_two = {
        "body": [(width - 3, height // 2), (width - 2, height // 2), (width - 1, height // 2)],
        "direction": "LEFT",
        "pending_direction": "LEFT",
        "health": config["starting_health"],
        "score": 0,
        "grow_pending": 0,
        "move_interval_ticks": 1,
        "move_tick_counter": 0,
        "slow_ticks_remaining": 0,
        "stun_ticks_remaining": 0,
        "resume_direction": None,
    }

    obstacles = [
        (width // 2, height // 2 - 2),
        (width // 2, height // 2 - 1),
        (width // 2, height // 2),
        (width // 2, height // 2 + 1),
    ]

    match = {
        "id": match_id,
        "players": [player_one, player_two],
        "status": "running",
        "winner": None,
        "reason": None,
        "tick": 0,
        "remaining_ticks": config["duration_seconds"] * config["tick_rate"],
        "snakes": {
            player_one: snake_one,
            player_two: snake_two,
        },
        "obstacles": obstacles,
        "pies": [],
        "cheers": [],
    }

    spawn_pie(match, config)
    return match


#adds one pie in a free grid cell that is not occupied by snakes or obstacles.
def spawn_pie(match, config):
    width = config["grid_width"]
    height = config["grid_height"]

    occupied = set(match["obstacles"])
    for snake in match["snakes"].values():
        occupied.update(snake["body"])

    if len(occupied) >= width * height:
        return

    while True:
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        if (x, y) not in occupied:
            pie_kind = random.choice(["orange", "green", "blue", "purple"])
            pie_value = 1 if pie_kind == "orange" else config["pie_heal"] if pie_kind == "green" else 0
            match["pies"] = [{"x": x, "y": y, "kind": pie_kind, "value": pie_value}]
            return
