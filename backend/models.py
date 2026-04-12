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


#returns true when one cell falls inside the protected corner zones.
def is_in_corner_zone(x, y, width, height, corner_margin):
    if x < corner_margin and y < corner_margin:
        return True
    if x >= width - corner_margin and y < corner_margin:
        return True
    if x < corner_margin and y >= height - corner_margin:
        return True
    if x >= width - corner_margin and y >= height - corner_margin:
        return True
    return False


#returns one random obstacle shape as relative cell offsets.
def pick_random_shape_offsets():
    return random.choice(
        [
            [(0, 0), (1, 0)],  # pair horizontal
            [(0, 0), (0, 1)],  # pair vertical
            [(0, 0), (1, 0), (2, 0)],  # triple horizontal
            [(0, 0), (0, 1), (0, 2)],  # triple vertical
            [(0, 0), (1, 0), (0, 1), (1, 1)],  # square
            [(0, 0), (1, 0), (2, 0), (3, 0)],  # wall horizontal
            [(0, 0), (0, 1), (0, 2), (0, 3)],  # wall vertical
        ]
    )


#returns true when any candidate cell touches an occupied cell by one grid step.
def touches_occupied(candidate_cells, occupied):
    for x, y in candidate_cells:
        neighbors = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        for neighbor in neighbors:
            if neighbor in occupied:
                return True
    return False


#returns one flattened obstacle list from grouped obstacle shapes.
def flatten_obstacle_shapes(obstacle_shapes):
    flattened = []
    for shape in obstacle_shapes:
        flattened.extend(shape)
    return flattened


#returns one random obstacle shape that fits without touching occupied cells.
def find_random_obstacle_shape(width, height, occupied, corner_margin=4, placement_attempts=800):
    for _ in range(placement_attempts):
        offsets = pick_random_shape_offsets()
        anchor_x = random.randint(0, width - 1)
        anchor_y = random.randint(0, height - 1)
        shape_cells = []
        valid = True

        for dx, dy in offsets:
            x = anchor_x + dx
            y = anchor_y + dy
            if x < 0 or x >= width or y < 0 or y >= height:
                valid = False
                break
            if (x, y) in occupied:
                valid = False
                break
            if is_in_corner_zone(x, y, width, height, corner_margin):
                valid = False
                break
            shape_cells.append((x, y))

        if not valid:
            continue

        if touches_occupied(shape_cells, occupied):
            continue

        return shape_cells

    return None


#builds up to five random obstacle shapes while keeping corners and spawn lanes clear.
def generate_random_obstacles(width, height, forbidden_positions):
    occupied = set(forbidden_positions)
    obstacle_shapes = []
    max_shapes = 5
    corner_margin = 4
    target_shapes = random.randint(3, max_shapes)

    while len(obstacle_shapes) < target_shapes:
        shape_cells = find_random_obstacle_shape(width, height, occupied, corner_margin)
        if shape_cells is None:
            break
        obstacle_shapes.append(shape_cells)
        occupied.update(shape_cells)

    return flatten_obstacle_shapes(obstacle_shapes[:max_shapes])


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
        "pies_collected": 0,
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
        "pies_collected": 0,
        "grow_pending": 0,
        "move_interval_ticks": 1,
        "move_tick_counter": 0,
        "slow_ticks_remaining": 0,
        "stun_ticks_remaining": 0,
        "resume_direction": None,
    }

    forbidden = set(snake_one["body"]) | set(snake_two["body"])
    obstacle_shapes = []
    occupied = set(forbidden)
    target_shapes = random.randint(3, 5)
    while len(obstacle_shapes) < target_shapes:
        shape_cells = find_random_obstacle_shape(width, height, occupied)
        if shape_cells is None:
            break
        obstacle_shapes.append(shape_cells)
        occupied.update(shape_cells)

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
        "obstacle_shapes": obstacle_shapes,
        "obstacles": flatten_obstacle_shapes(obstacle_shapes),
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


#tries to add one new random obstacle shape into an active match.
def add_random_obstacle(match, config):
    obstacle_shapes = match.setdefault("obstacle_shapes", [])
    max_shapes = config.get("max_obstacle_shapes", 5)
    if len(obstacle_shapes) >= max_shapes:
        return False

    occupied = set(match.get("obstacles", []))
    for snake in match["snakes"].values():
        occupied.update(snake["body"])
    for pie in match.get("pies", []):
        occupied.add((pie["x"], pie["y"]))

    shape_cells = find_random_obstacle_shape(
        config["grid_width"],
        config["grid_height"],
        occupied,
    )
    if shape_cells is None:
        return False

    obstacle_shapes.append(shape_cells)
    match["obstacles"] = flatten_obstacle_shapes(obstacle_shapes)
    return True
