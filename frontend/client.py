"""Pygame frontend client for ΠThon Arena."""

import queue
import socket
import threading

import pygame

from .net_utils import decode_message, encode_message
from .ui import UIButton, STATE_PRESSED


WIDTH = 1000
HEIGHT = 700
FPS = 60

PANEL_WIDTH = 280
GRID_MARGIN = 20
BOARD_BG = (20, 24, 30)
WHITE = (240, 240, 240)
BLACK = (0, 0, 0)
GREEN = (90, 220, 110)
RED = (230, 90, 90)
BLUE = (80, 150, 255)
ORANGE = (255, 170, 70)
YELLOW = (255, 220, 70)
GRAY = (130, 130, 130)
DARK_GRAY = (70, 70, 70)

SCREEN_CONNECT = "CONNECT"
SCREEN_USERNAME = "USERNAME"
SCREEN_LOBBY = "LOBBY"
SCREEN_GAME = "GAME"
SCREEN_GAME_OVER = "GAME_OVER"

BUTTON_WIDTH = 260
BUTTON_HEIGHT = 56


#returns initial mutable client state used by the pygame loop.
def create_client_state():
    return {
        "screen": SCREEN_CONNECT,
        "socket": None,
        "connected": False,
        "network_thread": None,
        "network_queue": queue.Queue(),
        "send_lock": threading.Lock(),
        "stop_event": threading.Event(),
        "recv_buffer": b"",
        "server_ip": "127.0.0.1",
        "server_port": "5000",
        "username": "",
        "self_name": None,
        "online_users": [],
        "selected_user_index": 0,
        "pending_challenger": None,
        "lobby_info": "Press C to challenge selected user",
        "input_focus": "ip",
        "error_text": "",
        "match": None,
        "is_spectator": False,
        "game_over": None,
        "connection_id": 0,
        "buttons": {},
    }


#creates screen-specific button objects used by the frontend UI.
def create_screen_buttons(font):
    return {
        SCREEN_CONNECT: {
            "connect": UIButton(
                40,
                260,
                BUTTON_WIDTH,
                BUTTON_HEIGHT,
                "Connect",
                font,
                image_idle_path="frontend/assets/ui/btn_primary_idle.png",
                image_hover_path="frontend/assets/ui/btn_primary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_primary_pressed.png",
                base_color=BLUE,
            ),
        },
        SCREEN_USERNAME: {
            "login": UIButton(
                40,
                200,
                BUTTON_WIDTH,
                BUTTON_HEIGHT,
                "Login",
                font,
                image_idle_path="frontend/assets/ui/btn_primary_idle.png",
                image_hover_path="frontend/assets/ui/btn_primary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_primary_pressed.png",
                base_color=BLUE,
            ),
        },
        SCREEN_LOBBY: {
            "challenge": UIButton(
                500, 
                300, 
                300, 
                75, 
                "Challenge", 
                font,
                image_idle_path="frontend/assets/ui/btn_secondary_idle.png",
                image_hover_path="frontend/assets/ui/btn_secondary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_secondary_pressed.png", 
                base_color=BLUE),
            "accept": UIButton(
                600, 
                380, 
                300, 
                75, 
                "Accept", 
                font, 
                image_idle_path="frontend/assets/ui/btn_secondary_idle.png",
                image_hover_path="frontend/assets/ui/btn_secondary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_secondary_pressed.png",
                base_color=GREEN),
            "wait": UIButton(
                520, 
                460, 
                300, 
                75, 
                "Wait", 
                font,
                image_idle_path="frontend/assets/ui/btn_secondary_idle.png",
                image_hover_path="frontend/assets/ui/btn_secondary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_secondary_pressed.png",                 
                base_color=(210, 160, 70)),
            "watch": UIButton(
                620, 
                540, 
                300, 
                75, 
                "Watch", 
                font, 
                image_idle_path="frontend/assets/ui/btn_secondary_idle.png",
                image_hover_path="frontend/assets/ui/btn_secondary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_secondary_pressed.png",                
                base_color=(160, 120, 210)),
        },
        SCREEN_GAME_OVER: {
            "to_lobby": UIButton(
                40, 
                320, 
                320, 
                62, 
                "Return To Lobby", 
                font,
                image_idle_path="frontend/assets/ui/btn_secondary_idle.png",
                image_hover_path="frontend/assets/ui/btn_secondary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_secondary_pressed.png",                 
                base_color=BLUE),
        },
    }


#safely sends one protocol message to the server.
def send_to_server(state, message_type, payload=None):
    if state["socket"] is None:
        return

    packet = encode_message(message_type, payload)
    with state["send_lock"]:
        try:
            state["socket"].sendall(packet)
        except OSError:
            state["error_text"] = "Connection lost while sending"
            state["connected"] = False


#reads socket data for one specific connection id and enqueues tagged messages.
def network_listener(state, connection_id):
    sock = state["socket"]
    recv_buffer = b""
    while not state["stop_event"].is_set():
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            break

        if not chunk:
            break

        recv_buffer += chunk

        while b"\n" in recv_buffer:
            line, _, rest = recv_buffer.partition(b"\n")
            recv_buffer = rest

            if not line.strip():
                continue

            try:
                message = decode_message(line.strip())
                state["network_queue"].put({"connection_id": connection_id, "message": message})
            except Exception:
                state["network_queue"].put({
                    "connection_id": connection_id,
                    "message": {"type": "ERROR", "payload": {"reason": "Invalid message from server"}},
                })

    state["network_queue"].put({"connection_id": connection_id, "message": {"type": "DISCONNECTED", "payload": {}}})


#opens a socket connection and starts the network listener thread.
def connect_to_server(state):
    if state["socket"] is not None:
        close_connection(state)

    try:
        port = int(state["server_port"].strip())
    except ValueError:
        state["error_text"] = "Port must be a number"
        return

    ip = state["server_ip"].strip()
    if not ip:
        state["error_text"] = "IP cannot be empty"
        return

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect((ip, port))
    except OSError:
        state["error_text"] = "Could not connect to server"
        return

    state["socket"] = sock
    state["connected"] = True
    state["stop_event"].clear()
    state["recv_buffer"] = b""
    state["network_queue"] = queue.Queue()
    state["connection_id"] += 1
    connection_id = state["connection_id"]
    state["network_thread"] = threading.Thread(target=network_listener, args=(state, connection_id), daemon=True)
    state["network_thread"].start()
    state["screen"] = SCREEN_USERNAME
    state["error_text"] = ""


#closes socket resources and stops background network thread.
def close_connection(state):
    state["stop_event"].set()

    if state["socket"] is not None:
        try:
            state["socket"].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            state["socket"].close()
        except OSError:
            pass

    state["socket"] = None
    state["connected"] = False
    state["recv_buffer"] = b""

    thread = state["network_thread"]
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=0.3)
    state["network_thread"] = None


#submits login to server using the username currently typed by the user.
def submit_login(state):
    username = state["username"].strip()
    if not username:
        state["error_text"] = "Username cannot be empty"
        return
    send_to_server(state, "LOGIN", {"username": username})


#handles one incoming server message and updates client state.
def handle_server_message(state, message):
    message_type = message["type"]
    payload = message["payload"]

    if message_type == "LOGIN_OK":
        state["self_name"] = payload.get("username")
        state["screen"] = SCREEN_LOBBY
        state["error_text"] = ""
        state["lobby_info"] = "Login successful"
        return

    if message_type == "LOGIN_REJECT":
        state["error_text"] = payload.get("reason", "Login rejected")
        return

    if message_type == "ONLINE_USERS":
        users = payload.get("users", [])
        if isinstance(users, list):
            state["online_users"] = users
            if state["selected_user_index"] >= len(users):
                state["selected_user_index"] = 0
        return

    if message_type == "CHALLENGE_RECEIVED":
        challenger = payload.get("from")
        if challenger:
            state["pending_challenger"] = challenger
            state["lobby_info"] = f"Challenge from {challenger}. Press A to accept"
        return

    if message_type == "CHALLENGE_PLAYER":
        state["lobby_info"] = "Challenge sent"
        return

    if message_type == "WAITING":
        state["lobby_info"] = "You are in waiting state"
        return

    if message_type == "MATCH_START":
        match = payload.get("match")
        if isinstance(match, dict):
            state["match"] = match
            state["is_spectator"] = bool(payload.get("spectator", False))
            state["screen"] = SCREEN_GAME
            state["game_over"] = None
            state["error_text"] = ""
        return

    if message_type == "STATE_UPDATE":
        match = payload.get("match")
        if isinstance(match, dict):
            state["match"] = match
        return

    if message_type == "GAME_OVER":
        state["game_over"] = {
            "winner": payload.get("winner"),
            "reason": payload.get("reason"),
        }
        match = payload.get("match")
        if isinstance(match, dict):
            state["match"] = match
        state["screen"] = SCREEN_GAME_OVER
        return

    if message_type == "ERROR":
        state["error_text"] = payload.get("reason", "Server error")
        return

    if message_type == "DISCONNECTED":
        state["error_text"] = "Disconnected from server"
        state["screen"] = SCREEN_CONNECT
        state["self_name"] = None
        state["match"] = None
        state["pending_challenger"] = None
        close_connection(state)


#pulls and processes all queued network messages for this frame.
def process_network_queue(state):
    while True:
        try:
            item = state["network_queue"].get_nowait()
        except queue.Empty:
            break

        if isinstance(item, dict) and "message" in item and "connection_id" in item:
            if item["connection_id"] != state["connection_id"]:
                continue
            handle_server_message(state, item["message"])
            continue

        handle_server_message(state, item)


#handles text input and actions while on the connect screen.
def handle_connect_screen_event(state, event):
    if event.type != pygame.KEYDOWN:
        return

    if event.key == pygame.K_TAB:
        state["input_focus"] = "port" if state["input_focus"] == "ip" else "ip"
        return

    if event.key == pygame.K_RETURN:
        press_button_feedback(state, "connect")
        connect_to_server(state)
        return

    if event.key == pygame.K_BACKSPACE:
        if state["input_focus"] == "ip":
            state["server_ip"] = state["server_ip"][:-1]
        else:
            state["server_port"] = state["server_port"][:-1]
        return

    if event.unicode and event.unicode.isprintable():
        if state["input_focus"] == "ip" and len(state["server_ip"]) < 40:
            state["server_ip"] += event.unicode
        if state["input_focus"] == "port" and len(state["server_port"]) < 8:
            state["server_port"] += event.unicode


#handles text input and login submit on the username screen.
def handle_username_screen_event(state, event):
    if event.type != pygame.KEYDOWN:
        return

    if event.key == pygame.K_RETURN:
        press_button_feedback(state, "login")
        submit_login(state)
        return

    if event.key == pygame.K_BACKSPACE:
        state["username"] = state["username"][:-1]
        return

    if event.unicode and event.unicode.isprintable() and len(state["username"]) < 20:
        state["username"] += event.unicode


#returns selected username from lobby list while skipping current self user.
def get_selected_lobby_user(state):
    users = [name for name in state["online_users"] if name != state["self_name"]]
    if not users:
        return None
    index = max(0, min(state["selected_user_index"], len(users) - 1))
    state["selected_user_index"] = index
    return users[index]


#handles lobby shortcuts for challenge, accept, wait, and watch.
def handle_lobby_screen_event(state, event):
    if event.type != pygame.KEYDOWN:
        return

    users = [name for name in state["online_users"] if name != state["self_name"]]

    if event.key == pygame.K_UP and users:
        state["selected_user_index"] = (state["selected_user_index"] - 1) % len(users)
        return

    if event.key == pygame.K_DOWN and users:
        state["selected_user_index"] = (state["selected_user_index"] + 1) % len(users)
        return

    if event.key == pygame.K_c:
        press_button_feedback(state, "challenge")
        target = get_selected_lobby_user(state)
        if target is None:
            state["lobby_info"] = "No player selected"
            return
        send_to_server(state, "CHALLENGE_PLAYER", {"target": target})
        return

    if event.key == pygame.K_a:
        press_button_feedback(state, "accept")
        if not state["pending_challenger"]:
            state["lobby_info"] = "No pending challenge"
            return
        send_to_server(state, "CHALLENGE_ACCEPT", {"from": state["pending_challenger"]})
        state["pending_challenger"] = None
        state["lobby_info"] = "Challenge accepted"
        return

    if event.key == pygame.K_w:
        press_button_feedback(state, "wait")
        send_to_server(state, "WAITING", {})
        return

    if event.key == pygame.K_v:
        press_button_feedback(state, "watch")
        send_to_server(state, "WATCH_MATCH", {})


#handles gameplay controls and non-gameplay shortcuts.
def handle_game_screen_event(state, event):
    if event.type != pygame.KEYDOWN:
        return

    if event.key == pygame.K_ESCAPE:
        state["screen"] = SCREEN_LOBBY
        return

    if state["is_spectator"]:
        return

    if event.key == pygame.K_UP:
        send_to_server(state, "INPUT", {"direction": "UP"})
    elif event.key == pygame.K_DOWN:
        send_to_server(state, "INPUT", {"direction": "DOWN"})
    elif event.key == pygame.K_LEFT:
        send_to_server(state, "INPUT", {"direction": "LEFT"})
    elif event.key == pygame.K_RIGHT:
        send_to_server(state, "INPUT", {"direction": "RIGHT"})


#handles restart navigation after game over.
def handle_game_over_screen_event(state, event):
    if event.type == pygame.KEYDOWN and event.key == pygame.K_l:
        press_button_feedback(state, "to_lobby")
        state["screen"] = SCREEN_LOBBY


#shows pressed-state feedback for a screen button action.
def press_button_feedback(state, action_name):
    buttons = state["buttons"].get(state["screen"], {})
    button = buttons.get(action_name)
    if button is None:
        return
    if hasattr(button, "trigger_press_feedback"):
        button.trigger_press_feedback()
        return
    button.state = STATE_PRESSED


#runs one button action by name for the current screen.
def run_button_action(state, action_name):
    if state["screen"] == SCREEN_CONNECT and action_name == "connect":
        connect_to_server(state)
        return

    if state["screen"] == SCREEN_USERNAME and action_name == "login":
        submit_login(state)
        return

    if state["screen"] == SCREEN_LOBBY and action_name == "challenge":
        target = get_selected_lobby_user(state)
        if target is None:
            state["lobby_info"] = "No player selected"
            return
        send_to_server(state, "CHALLENGE_PLAYER", {"target": target})
        return

    if state["screen"] == SCREEN_LOBBY and action_name == "accept":
        if state["pending_challenger"]:
            send_to_server(state, "CHALLENGE_ACCEPT", {"from": state["pending_challenger"]})
            state["pending_challenger"] = None
            state["lobby_info"] = "Challenge accepted"
        else:
            state["lobby_info"] = "No pending challenge"
        return

    if state["screen"] == SCREEN_LOBBY and action_name == "wait":
        send_to_server(state, "WAITING", {})
        return

    if state["screen"] == SCREEN_LOBBY and action_name == "watch":
        send_to_server(state, "WATCH_MATCH", {})
        return

    if state["screen"] == SCREEN_GAME_OVER and action_name == "to_lobby":
        state["screen"] = SCREEN_LOBBY


#updates all visible buttons for the current screen and triggers clicks.
def update_screen_buttons(state):
    buttons = state["buttons"].get(state["screen"], {})
    if not buttons:
        return

    mouse_pos = pygame.mouse.get_pos()
    mouse_down = pygame.mouse.get_pressed()[0]

    for action_name, button in buttons.items():
        if button.update(mouse_pos, mouse_down):
            run_button_action(state, action_name)


#draws all visible buttons for the current screen.
def draw_screen_buttons(screen, state):
    buttons = state["buttons"].get(state["screen"], {})
    for button in buttons.values():
        button.draw(screen)


#dispatches pygame events to the active screen handler.
def handle_event(state, event):
    if event.type == pygame.QUIT:
        return False

    if state["screen"] == SCREEN_CONNECT:
        handle_connect_screen_event(state, event)
    elif state["screen"] == SCREEN_USERNAME:
        handle_username_screen_event(state, event)
    elif state["screen"] == SCREEN_LOBBY:
        handle_lobby_screen_event(state, event)
    elif state["screen"] == SCREEN_GAME:
        handle_game_screen_event(state, event)
    elif state["screen"] == SCREEN_GAME_OVER:
        handle_game_over_screen_event(state, event)

    return True


#draws one line of text and returns next y position for chained drawing.
def draw_text_line(screen, font, text, color, x, y):
    surface = font.render(text, True, color)
    screen.blit(surface, (x, y))
    return y + surface.get_height() + 6


#draws the connect screen with editable ip and port fields.
def draw_connect_screen(screen, font, big_font, state):
    screen.fill(BOARD_BG)
    y = 80
    y = draw_text_line(screen, big_font, "PiThon Arena Client", WHITE, 40, y)
    y += 20

    ip_label = ">" if state["input_focus"] == "ip" else " "
    port_label = ">" if state["input_focus"] == "port" else " "
    y = draw_text_line(screen, font, f"{ip_label} Server IP: {state['server_ip']}", WHITE, 40, y)
    y = draw_text_line(screen, font, f"{port_label} Server Port: {state['server_port']}", WHITE, 40, y)
    y += 10

    y = draw_text_line(screen, font, "Tab: switch field", GRAY, 40, y)
    y = draw_text_line(screen, font, "Enter: connect", GRAY, 40, y)

    if state["error_text"]:
        draw_text_line(screen, font, state["error_text"], RED, 40, y + 16)

    draw_screen_buttons(screen, state)


#draws the username login screen.
def draw_username_screen(screen, font, big_font, state):
    screen.fill(BOARD_BG)
    y = 80
    y = draw_text_line(screen, big_font, "Choose Username", WHITE, 40, y)
    y += 20

    y = draw_text_line(screen, font, f"Username: {state['username']}", WHITE, 40, y)
    y = draw_text_line(screen, font, "Enter: login", GRAY, 40, y + 10)

    if state["error_text"]:
        draw_text_line(screen, font, state["error_text"], RED, 40, y + 46)

    draw_screen_buttons(screen, state)


#draws lobby content including online users and matchmaking controls.
def draw_lobby_screen(screen, font, big_font, state):
    screen.fill(BOARD_BG)
    y = 30
    y = draw_text_line(screen, big_font, f"Lobby - {state['self_name']}", WHITE, 20, y)
    y = draw_text_line(screen, font, state["lobby_info"], YELLOW, 20, y)

    users = [name for name in state["online_users"] if name != state["self_name"]]
    y += 8
    y = draw_text_line(screen, font, "Online Players:", WHITE, 20, y)

    if not users:
        y = draw_text_line(screen, font, "No other players online", GRAY, 20, y)
    else:
        for index, user in enumerate(users):
            prefix = "> " if index == state["selected_user_index"] else "  "
            color = BLUE if index == state["selected_user_index"] else WHITE
            y = draw_text_line(screen, font, f"{prefix}{user}", color, 20, y)

    y += 10
    y = draw_text_line(screen, font, "Use buttons or keys (C/A/W/V)", GRAY, 20, y)
    y = draw_text_line(screen, font, "Challenge / Accept / Wait / Watch", GRAY, 20, y)

    if state["pending_challenger"]:
        draw_text_line(screen, font, f"Incoming: {state['pending_challenger']}", ORANGE, 20, y + 16)

    if state["error_text"]:
        draw_text_line(screen, font, state["error_text"], RED, 20, HEIGHT - 36)

    draw_screen_buttons(screen, state)


#returns board geometry derived from current match dimensions.
def get_board_geometry(match):
    grid_width = 30
    grid_height = 20
    if isinstance(match, dict):
        snakes = match.get("snakes", {})
        if snakes:
            # keep default geometry from backend config expectations.
            grid_width = 30
            grid_height = 20

    board_width_pixels = WIDTH - PANEL_WIDTH - 2 * GRID_MARGIN
    board_height_pixels = HEIGHT - 2 * GRID_MARGIN
    cell_size = min(board_width_pixels // grid_width, board_height_pixels // grid_height)
    board_width = cell_size * grid_width
    board_height = cell_size * grid_height

    return {
        "grid_width": grid_width,
        "grid_height": grid_height,
        "cell_size": cell_size,
        "x": GRID_MARGIN,
        "y": GRID_MARGIN,
        "pixel_width": board_width,
        "pixel_height": board_height,
    }


#draws the active game board from server-authoritative match state.
def draw_game_board(screen, state, font, small_font):
    match = state["match"]
    if not isinstance(match, dict):
        draw_text_line(screen, font, "Waiting for match state...", WHITE, 20, 40)
        return

    geo = get_board_geometry(match)
    board_rect = pygame.Rect(geo["x"], geo["y"], geo["pixel_width"], geo["pixel_height"])

    pygame.draw.rect(screen, (18, 18, 24), board_rect)
    pygame.draw.rect(screen, DARK_GRAY, board_rect, 2)

    for obstacle in match.get("obstacles", []):
        ox = geo["x"] + obstacle["x"] * geo["cell_size"]
        oy = geo["y"] + obstacle["y"] * geo["cell_size"]
        rect = pygame.Rect(ox, oy, geo["cell_size"], geo["cell_size"])
        pygame.draw.rect(screen, GRAY, rect)

    for pie in match.get("pies", []):
        px = geo["x"] + pie["x"] * geo["cell_size"] + geo["cell_size"] // 2
        py = geo["y"] + pie["y"] * geo["cell_size"] + geo["cell_size"] // 2
        radius = max(3, geo["cell_size"] // 3)
        pygame.draw.circle(screen, ORANGE, (px, py), radius)

    snake_items = list(match.get("snakes", {}).items())
    for index, (username, snake) in enumerate(snake_items):
        color = GREEN if index == 0 else BLUE
        for pos_index, segment in enumerate(snake.get("body", [])):
            sx = geo["x"] + segment["x"] * geo["cell_size"]
            sy = geo["y"] + segment["y"] * geo["cell_size"]
            rect = pygame.Rect(sx, sy, geo["cell_size"], geo["cell_size"])
            if pos_index == 0:
                pygame.draw.rect(screen, color, rect)
            else:
                pygame.draw.rect(screen, tuple(max(20, c - 40) for c in color), rect)

    panel_x = geo["x"] + geo["pixel_width"] + 20
    panel_y = 30
    panel_y = draw_text_line(screen, font, "Match Info", WHITE, panel_x, panel_y)
    panel_y = draw_text_line(screen, small_font, f"Tick: {match.get('tick', 0)}", WHITE, panel_x, panel_y)
    panel_y = draw_text_line(screen, small_font, f"Time left: {match.get('remaining_seconds', 0)}", WHITE, panel_x, panel_y)

    players = match.get("players", [])
    snakes = match.get("snakes", {})

    panel_y += 10
    for index, username in enumerate(players):
        snake = snakes.get(username, {})
        health = snake.get("health", 0)
        color = GREEN if index == 0 else BLUE
        panel_y = draw_text_line(screen, small_font, f"{username}", color, panel_x, panel_y)
        panel_y = draw_text_line(screen, small_font, f"Health: {health}", WHITE, panel_x, panel_y)
        panel_y += 6

    panel_y += 8
    if state["is_spectator"]:
        panel_y = draw_text_line(screen, small_font, "Mode: Spectator", YELLOW, panel_x, panel_y)
    else:
        panel_y = draw_text_line(screen, small_font, "Arrows: move snake", WHITE, panel_x, panel_y)
    draw_text_line(screen, small_font, "Esc: back to lobby", WHITE, panel_x, panel_y)


#draws the game screen including board and contextual status text.
def draw_game_screen(screen, font, big_font, small_font, state):
    screen.fill(BOARD_BG)
    draw_text_line(screen, big_font, "Snake Arena Match", WHITE, 20, 8)
    draw_game_board(screen, state, font, small_font)

    if state["error_text"]:
        draw_text_line(screen, small_font, state["error_text"], RED, 20, HEIGHT - 30)


#draws the game-over screen with winner information.
def draw_game_over_screen(screen, font, big_font, state):
    screen.fill(BOARD_BG)
    y = 120
    y = draw_text_line(screen, big_font, "Game Over", WHITE, 40, y)

    game_over = state["game_over"] or {}
    winner = game_over.get("winner")
    reason = game_over.get("reason")

    winner_text = "Draw" if winner is None else f"Winner: {winner}"
    y = draw_text_line(screen, font, winner_text, YELLOW, 40, y + 20)
    y = draw_text_line(screen, font, f"Reason: {reason}", WHITE, 40, y)
    y = draw_text_line(screen, font, "Press L or click button to return", GRAY, 40, y + 20)

    draw_screen_buttons(screen, state)


#renders the currently active screen.
def render_screen(screen, font, big_font, small_font, state):
    if state["screen"] == SCREEN_CONNECT:
        draw_connect_screen(screen, font, big_font, state)
    elif state["screen"] == SCREEN_USERNAME:
        draw_username_screen(screen, font, big_font, state)
    elif state["screen"] == SCREEN_LOBBY:
        draw_lobby_screen(screen, font, big_font, state)
    elif state["screen"] == SCREEN_GAME:
        draw_game_screen(screen, font, big_font, small_font, state)
    elif state["screen"] == SCREEN_GAME_OVER:
        draw_game_over_screen(screen, font, big_font, state)


#runs the main pygame frontend loop.
def run_client():
    pygame.init()

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("PiThon Arena Frontend")
    clock = pygame.time.Clock()

    font = pygame.font.SysFont("consolas", 24)
    big_font = pygame.font.SysFont("consolas", 34)
    small_font = pygame.font.SysFont("consolas", 20)

    state = create_client_state()
    state["buttons"] = create_screen_buttons(font)

    running = True
    while running:
        clock.tick(FPS)

        process_network_queue(state)
        update_screen_buttons(state)

        for event in pygame.event.get():
            running = handle_event(state, event)
            if not running:
                break

        render_screen(screen, font, big_font, small_font, state)
        pygame.display.update()

    close_connection(state)
    pygame.quit()


#starts the frontend client application.
def main():
    run_client()


if __name__ == "__main__":
    main()
