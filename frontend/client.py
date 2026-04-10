"""Pygame frontend client for ΠThon Arena."""

import os
import queue
import socket
import threading

import pygame

from .net_utils import decode_message, encode_message
from .ui import UIButton, STATE_PRESSED


WIDTH = 1300
HEIGHT = 700
FPS = 60

PANEL_WIDTH = 280
GRID_MARGIN = 20
BOARD_TOP_SPACE = 80
BOARD_BOTTOM_SPACE = 40
HEALTH_BAR_WIDTH = 320
HEALTH_BAR_HEIGHT = 26
CHAT_PANEL_WIDTH = 320
CHAT_MAX_VISIBLE = 14
BOARD_BG = (20, 24, 30)
WHITE = (240, 240, 240)
BLACK = (0, 0, 0)
GREEN = (90, 220, 110)
RED = (230, 90, 90)
BLUE = (80, 150, 255)
ORANGE = (255, 170, 70)
YELLOW = (255, 220, 70)
PURPLE = (185, 110, 255)
GRAY = (130, 130, 130)
DARK_GRAY = (70, 70, 70)
MENU_TEXT_COLOR = (245, 245, 245)
MENU_HINT_COLOR = (255, 235, 140)

SCREEN_CONNECT = "CONNECT"
SCREEN_USERNAME = "USERNAME"
SCREEN_LOBBY = "LOBBY"
SCREEN_GAME = "GAME"
SCREEN_GAME_OVER = "GAME_OVER"

BUTTON_WIDTH = 260
BUTTON_HEIGHT = 56
CHEER_OPTIONS = ["gg", "go blue", "go green", "ya sayi2", "mal3abak"]
MENU_BACKGROUND_PATH = "frontend/assets/backgrounds/menu_background.png"
ARENA_FRAME_BG_PATH = "frontend/assets/arena/arena_frame_bg.png"
ARENA_FLOOR_PATH = "frontend/assets/arena/arena_floor.png"
CHAT_PANEL_BG_PATH = "frontend/assets/ui/chat_panel_bg.png"
HUD_BAR_BG_PATH = "frontend/assets/hud/hud_bar_bg.png"
CHAT_INPUT_BG_PATH = "frontend/assets/ui/chat_input_bg.png"
MENU_TEXT_X = 100
MENU_TEXT_Y = 100
LOBBY_TEXT_X = 100
LOBBY_TEXT_Y = 50
MAX_CHAT_INPUT_LENGTH = 120


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
        "active_matches": [],
        "selected_user_index": 0,
        "selected_match_index": 0,
        "pending_challenger": None,
        "lobby_info": "Press C to challenge selected user",
        "input_focus": "ip",
        "error_text": "",
        "match": None,
        "is_spectator": False,
        "chat_input": "",
        "game_over": None,
        "connection_id": 0,
        "scaled_surface_cache": {},
        "buttons": {},
    }


#creates screen-specific button objects used by the frontend UI.
def create_screen_buttons(font):
    return {
        SCREEN_CONNECT: {
            "connect": UIButton(
                150,
                320,
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
                150,
                300,
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
                600, 
                300, 
                75, 
                "Challenge", 
                font,
                image_idle_path="frontend/assets/ui/btn_secondary_idle.png",
                image_hover_path="frontend/assets/ui/btn_secondary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_secondary_pressed.png", 
                base_color=BLUE),
            "accept": UIButton(
                750, 
                550, 
                300, 
                75, 
                "Accept", 
                font, 
                image_idle_path="frontend/assets/ui/btn_secondary_idle.png",
                image_hover_path="frontend/assets/ui/btn_secondary_hover.png",
                image_pressed_path="frontend/assets/ui/btn_secondary_pressed.png",
                base_color=GREEN),
            "watch": UIButton(
                1000, 
                500, 
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
        active_matches = payload.get("active_matches", [])
        if isinstance(active_matches, list):
            state["active_matches"] = active_matches
            if state["selected_match_index"] >= len(active_matches):
                state["selected_match_index"] = 0
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
        state["lobby_info"] = "Waiting for challenge response"
        return

    if message_type == "MATCH_START":
        match = payload.get("match")
        if isinstance(match, dict):
            state["match"] = match
            state["is_spectator"] = bool(payload.get("spectator", False))
            state["chat_input"] = ""
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
            "pie_stats": payload.get("pie_stats", {}),
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


#returns selected active match object from lobby metadata list.
def get_selected_active_match(state):
    matches = state.get("active_matches", [])
    if not matches:
        return None
    index = max(0, min(state["selected_match_index"], len(matches) - 1))
    state["selected_match_index"] = index
    return matches[index]


#handles lobby shortcuts for challenge, accept, and watch.
def handle_lobby_screen_event(state, event):
    if event.type != pygame.KEYDOWN:
        return

    users = [name for name in state["online_users"] if name != state["self_name"]]
    matches = state.get("active_matches", [])

    if event.key == pygame.K_UP and users:
        state["selected_user_index"] = (state["selected_user_index"] - 1) % len(users)
        return

    if event.key == pygame.K_DOWN and users:
        state["selected_user_index"] = (state["selected_user_index"] + 1) % len(users)
        return

    if event.key == pygame.K_LEFT and matches:
        state["selected_match_index"] = (state["selected_match_index"] - 1) % len(matches)
        return

    if event.key == pygame.K_RIGHT and matches:
        state["selected_match_index"] = (state["selected_match_index"] + 1) % len(matches)
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

    if event.key == pygame.K_v:
        press_button_feedback(state, "watch")
        selected_match = get_selected_active_match(state)
        if selected_match is None:
            state["lobby_info"] = "No active match to watch"
            return
        send_to_server(state, "WATCH_MATCH", {"match_id": selected_match.get("id")})


#handles gameplay controls and non-gameplay shortcuts.
def handle_game_screen_event(state, event):
    if event.type != pygame.KEYDOWN:
        return

    if event.key == pygame.K_ESCAPE:
        state["screen"] = SCREEN_LOBBY
        state["chat_input"] = ""
        return

    if state["is_spectator"]:
        if event.key == pygame.K_RETURN:
            message = state["chat_input"].strip()
            if message:
                send_to_server(state, "CHEER", {"text": message})
                state["chat_input"] = ""
            return
        if event.key == pygame.K_BACKSPACE:
            state["chat_input"] = state["chat_input"][:-1]
            return
        if event.unicode and event.unicode.isprintable() and len(state["chat_input"]) < MAX_CHAT_INPUT_LENGTH:
            state["chat_input"] += event.unicode
        return

    if event.unicode in {"1", "2", "3", "4", "5"}:
        index = int(event.unicode) - 1
        send_to_server(state, "CHEER", {"text": CHEER_OPTIONS[index]})
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

    if state["screen"] == SCREEN_LOBBY and action_name == "watch":
        selected_match = get_selected_active_match(state)
        if selected_match is None:
            state["lobby_info"] = "No active match to watch"
            return
        send_to_server(state, "WATCH_MATCH", {"match_id": selected_match.get("id")})
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


#loads and scales the shared menu background image once at startup.
def load_menu_background():
    if not os.path.exists(MENU_BACKGROUND_PATH):
        return None
    image = pygame.image.load(MENU_BACKGROUND_PATH).convert()
    return pygame.transform.scale(image, (WIDTH, HEIGHT))


#loads one optional image surface from disk and returns None when missing.
def load_optional_surface(path, use_alpha=False):
    if not os.path.exists(path):
        return None
    image = pygame.image.load(path)
    if use_alpha:
        return image.convert_alpha()
    return image.convert()


#loads image assets used by the game screen UI.
def load_game_ui_assets():
    return {
        "arena_frame_bg": load_optional_surface(ARENA_FRAME_BG_PATH, use_alpha=False),
        "arena_floor": load_optional_surface(ARENA_FLOOR_PATH, use_alpha=False),
        "chat_panel_bg": load_optional_surface(CHAT_PANEL_BG_PATH, use_alpha=False),
        "hud_bar_bg": load_optional_surface(HUD_BAR_BG_PATH, use_alpha=True),
        "chat_input_bg": load_optional_surface(CHAT_INPUT_BG_PATH, use_alpha=True),
    }


#returns a scaled surface using a simple cache keyed by asset name and size.
def get_scaled_surface(state, cache_name, source_surface, width, height):
    if source_surface is None:
        return None

    cache = state.setdefault("scaled_surface_cache", {})
    key = (cache_name, width, height)
    if key not in cache:
        cache[key] = pygame.transform.scale(source_surface, (width, height))
    return cache[key]


#draws the menu background when available or uses the default fallback color.
def draw_menu_background(screen, state):
    background = state.get("menu_background")
    if background is not None:
        screen.blit(background, (0, 0))
    else:
        screen.fill(BOARD_BG)


#draws the connect screen with editable ip and port fields.
def draw_connect_screen(screen, font, big_font, state):
    draw_menu_background(screen, state)
    y = MENU_TEXT_Y
    y = draw_text_line(screen, big_font, "PiThon Arena Client", MENU_TEXT_COLOR, MENU_TEXT_X, y)
    y += 20

    ip_label = ">" if state["input_focus"] == "ip" else " "
    port_label = ">" if state["input_focus"] == "port" else " "
    y = draw_text_line(screen, font, f"{ip_label} Server IP: {state['server_ip']}", MENU_TEXT_COLOR, MENU_TEXT_X, y)
    y = draw_text_line(screen, font, f"{port_label} Server Port: {state['server_port']}", MENU_TEXT_COLOR, MENU_TEXT_X, y)
    y += 10

    y = draw_text_line(screen, font, "Tab: switch field", MENU_HINT_COLOR, MENU_TEXT_X, y)
    y = draw_text_line(screen, font, "Enter: connect", MENU_HINT_COLOR, MENU_TEXT_X, y)

    if state["error_text"]:
        draw_text_line(screen, font, state["error_text"], RED, MENU_TEXT_X, y + 16)

    draw_screen_buttons(screen, state)


#draws the username login screen.
def draw_username_screen(screen, font, big_font, state):
    draw_menu_background(screen, state)
    y = MENU_TEXT_Y
    y = draw_text_line(screen, big_font, "Choose Username", MENU_TEXT_COLOR, MENU_TEXT_X, y)
    y += 20

    y = draw_text_line(screen, font, f"Username: {state['username']}", MENU_TEXT_COLOR, MENU_TEXT_X, y)
    y = draw_text_line(screen, font, "Enter: login", MENU_HINT_COLOR, MENU_TEXT_X, y + 10)

    if state["error_text"]:
        draw_text_line(screen, font, state["error_text"], RED, MENU_TEXT_X, y + 46)

    draw_screen_buttons(screen, state)


#draws lobby content including online users and matchmaking controls.
def draw_lobby_screen(screen, font, big_font, state):
    draw_menu_background(screen, state)
    y = LOBBY_TEXT_Y
    y = draw_text_line(screen, big_font, f"Lobby - {state['self_name']}", MENU_TEXT_COLOR, LOBBY_TEXT_X, y)
    y = draw_text_line(screen, font, state["lobby_info"], MENU_HINT_COLOR, LOBBY_TEXT_X, y)

    in_game_players = set()
    for match in state.get("active_matches", []):
        for name in match.get("players", []):
            in_game_players.add(name)

    users = [name for name in state["online_users"] if name != state["self_name"]]
    ticks = 0
    if hasattr(pygame, "time") and hasattr(pygame.time, "get_ticks"):
        ticks = pygame.time.get_ticks()
    challenge_flicker_on = ((ticks // 400) % 2) == 0
    y += 8
    y = draw_text_line(screen, font, "Online Players:", MENU_TEXT_COLOR, LOBBY_TEXT_X, y)

    if not users:
        y = draw_text_line(screen, font, "No other players online", MENU_TEXT_COLOR, LOBBY_TEXT_X, y)
    else:
        for index, user in enumerate(users):
            prefix = "> " if index == state["selected_user_index"] else "  "
            normal_color = ORANGE if index == state["selected_user_index"] else WHITE
            color = normal_color
            has_incoming = state["pending_challenger"] == user
            if has_incoming:
                color = RED if challenge_flicker_on else normal_color
            status = " (IN GAME)" if user in in_game_players else ""
            label = f"{prefix}{user}{status}"
            name_surface = font.render(label, True, color)
            screen.blit(name_surface, (LOBBY_TEXT_X, y))
            if has_incoming:
                incoming_surface = font.render(" incoming challenge", True, color)
                screen.blit(incoming_surface, (LOBBY_TEXT_X + name_surface.get_width() + 8, y))
            y += name_surface.get_height() + 6

    y += 10
    y = draw_text_line(screen, font, "Active Matches:", MENU_TEXT_COLOR, LOBBY_TEXT_X, y)
    matches = state.get("active_matches", [])
    if not matches:
        y = draw_text_line(screen, font, "No active match", MENU_TEXT_COLOR, LOBBY_TEXT_X, y)
    else:
        for index, match in enumerate(matches):
            players = match.get("players", [])
            label = " vs ".join(players) if len(players) == 2 else "Unknown players"
            prefix = "> " if index == state["selected_match_index"] else "  "
            color = RED if index == state["selected_match_index"] else WHITE
            y = draw_text_line(screen, font, f"{prefix}Match #{match.get('id', '?')}: {label}", color, LOBBY_TEXT_X, y)

    y += 10
    y = draw_text_line(screen, font, "Use buttons or keys (C/A/V)", MENU_HINT_COLOR, LOBBY_TEXT_X, y)
    y = draw_text_line(screen, font, "Left/Right select match to watch", MENU_HINT_COLOR, LOBBY_TEXT_X, y)

    if state["error_text"]:
        draw_text_line(screen, font, state["error_text"], RED, LOBBY_TEXT_X, HEIGHT - 36)

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

    playable_width = WIDTH - CHAT_PANEL_WIDTH - 3 * GRID_MARGIN
    board_width_pixels = playable_width
    board_height_pixels = HEIGHT - BOARD_TOP_SPACE - BOARD_BOTTOM_SPACE
    cell_size = min(board_width_pixels // grid_width, board_height_pixels // grid_height)
    board_width = cell_size * grid_width
    board_height = cell_size * grid_height
    playable_x = GRID_MARGIN
    board_x = playable_x + (playable_width - board_width) // 2
    board_y = BOARD_TOP_SPACE + (board_height_pixels - board_height) // 2

    return {
        "grid_width": grid_width,
        "grid_height": grid_height,
        "cell_size": cell_size,
        "x": board_x,
        "y": board_y,
        "pixel_width": board_width,
        "pixel_height": board_height,
    }


#draws one horizontal health bar anchored to a top corner for one player.
def draw_corner_health_bar(screen, font, name_font, name_color, state, x, y, player_name, health_value):
    health_value = max(0, min(100, int(health_value)))

    text_surface = name_font.render(player_name, True, name_color)
    health_surface = font.render(f"Health: {health_value}", True, WHITE)

    panel_height = text_surface.get_height() + HEALTH_BAR_HEIGHT + health_surface.get_height() + 5
    assets = state.get("game_ui_assets", {})
    hud_bg = get_scaled_surface(state, "hud_bar_bg", assets.get("hud_bar_bg"), HEALTH_BAR_WIDTH, panel_height)
    if hud_bg is not None:
        screen.blit(hud_bg, (x, y + 4))
    else:
        fallback_rect = pygame.Rect(x, y, HEALTH_BAR_WIDTH, panel_height)
        pygame.draw.rect(screen, (26, 30, 38), fallback_rect)
        pygame.draw.rect(screen, DARK_GRAY, fallback_rect, 2)

    screen.blit(text_surface, (x + 8, y + 4))
    bar_top = y + text_surface.get_height() + 6
    outer_rect = pygame.Rect(x, bar_top, HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT)
    pygame.draw.rect(screen, DARK_GRAY, outer_rect)
    pygame.draw.rect(screen, WHITE, outer_rect, 2)

    fill_width = int((health_value / 100.0) * (HEALTH_BAR_WIDTH - 4))
    fill_rect = pygame.Rect(x + 2, bar_top + 2, fill_width, HEALTH_BAR_HEIGHT - 4)
    pygame.draw.rect(screen, GREEN, fill_rect)

    screen.blit(health_surface, (x + 8, bar_top + HEALTH_BAR_HEIGHT + 6))


#draws the right-side chat panel with recent messages and input/help sections.
def draw_chat_panel(screen, match, state, small_font):
    panel_x = WIDTH - CHAT_PANEL_WIDTH - GRID_MARGIN
    panel_y = GRID_MARGIN
    panel_h = HEIGHT - 2 * GRID_MARGIN
    panel_rect = pygame.Rect(panel_x, panel_y, CHAT_PANEL_WIDTH, panel_h)

    assets = state.get("game_ui_assets", {})
    panel_bg = get_scaled_surface(state, "chat_panel_bg", assets.get("chat_panel_bg"), CHAT_PANEL_WIDTH, panel_h)
    if panel_bg is not None:
        screen.blit(panel_bg, panel_rect.topleft)
    else:
        pygame.draw.rect(screen, (24, 28, 36), panel_rect)
        pygame.draw.rect(screen, DARK_GRAY, panel_rect, 2)

    text_y = panel_y + 12
    text_y = draw_text_line(screen, small_font, "Match Chat", WHITE, panel_x + 12, text_y)

    cheers = match.get("cheers", [])
    visible = cheers[-CHAT_MAX_VISIBLE:]
    if not visible:
        text_y = draw_text_line(screen, small_font, "No messages yet", GRAY, panel_x + 12, text_y + 4)
    else:
        for item in visible:
            sender = item.get("from", "?")
            text = item.get("text", "")
            text_y = draw_text_line(screen, small_font, f"{sender}: {text}", WHITE, panel_x + 12, text_y + 2)

    if state["is_spectator"]:
        draw_text_line(screen, small_font, "Spectator Chat:", YELLOW, panel_x + 12, panel_y + panel_h - 88)
        draw_text_line(screen, small_font, "Enter to send", MENU_HINT_COLOR, panel_x + 12, panel_y + panel_h - 64)
        input_rect = pygame.Rect(panel_x + 12, panel_y + panel_h - 42, CHAT_PANEL_WIDTH - 24, 28)
        input_bg = get_scaled_surface(state, "chat_input_bg", assets.get("chat_input_bg"), input_rect.width, input_rect.height)
        if input_bg is not None:
            screen.blit(input_bg, input_rect.topleft)
        else:
            pygame.draw.rect(screen, (18, 18, 18), input_rect)
            pygame.draw.rect(screen, WHITE, input_rect, 2)
        typed = state.get("chat_input", "")
        typed_surface = small_font.render(f"> {typed}", True, WHITE)
        screen.blit(typed_surface, (input_rect.x + 6, input_rect.y + 4))
    else:
        opt_y = panel_y + panel_h - 160
        draw_text_line(screen, small_font, "Quick Chat (1-5):", YELLOW, panel_x + 12, opt_y)
        for index, phrase in enumerate(CHEER_OPTIONS, start=1):
            opt_y += 26
            draw_text_line(screen, small_font, f"{index}. {phrase}", GRAY, panel_x + 12, opt_y)


#returns the render color for each pie kind.
def get_pie_color(pie_kind):
    if pie_kind == "green":
        return GREEN
    if pie_kind == "blue":
        return BLUE
    if pie_kind == "purple":
        return PURPLE
    return ORANGE


#draws one-line pie effect descriptions under the arena with colored circle markers.
def draw_pie_descriptions(screen, font, start_x, start_y):
    entries = [
        (ORANGE, "+5s"),
        (GREEN, "heal"),
        (BLUE, "slow opponent"),
        (PURPLE, "+1 length"),
    ]

    x = start_x
    y = start_y
    for color, label in entries:
        pygame.draw.circle(screen, color, (x + 7, y + 10), 6)
        text_surface = font.render(f": {label}", True, WHITE)
        screen.blit(text_surface, (x + 18, y))
        x += 18 + text_surface.get_width() + 18


#draws the active game board from server-authoritative match state.
def draw_game_board(screen, state, font, small_font):
    match = state["match"]
    if not isinstance(match, dict):
        draw_text_line(screen, font, "Waiting for match state...", WHITE, 20, 40)
        return

    geo = get_board_geometry(match)
    board_rect = pygame.Rect(geo["x"], geo["y"], geo["pixel_width"], geo["pixel_height"])

    assets = state.get("game_ui_assets", {})
    floor_bg = get_scaled_surface(state, "arena_floor", assets.get("arena_floor"), geo["pixel_width"], geo["pixel_height"])
    if floor_bg is not None:
        screen.blit(floor_bg, board_rect.topleft)
    else:
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
        pie_color = get_pie_color(pie.get("kind", "orange"))
        pygame.draw.circle(screen, pie_color, (px, py), radius)

    snake_items = list(match.get("snakes", {}).items())
    for index, (username, snake) in enumerate(snake_items):
        color = GREEN if index == 0 else BLUE
        is_flickering = snake.get("stun_ticks_remaining", 0) > 0 and match.get("tick", 0) % 2 == 0
        if is_flickering:
            color = WHITE
        for pos_index, segment in enumerate(snake.get("body", [])):
            sx = geo["x"] + segment["x"] * geo["cell_size"]
            sy = geo["y"] + segment["y"] * geo["cell_size"]
            rect = pygame.Rect(sx, sy, geo["cell_size"], geo["cell_size"])
            if pos_index == 0:
                pygame.draw.rect(screen, color, rect)
            else:
                pygame.draw.rect(screen, tuple(max(20, c - 40) for c in color), rect)

    snakes = match.get("snakes", {})
    players = match.get("players", [])
    if len(players) >= 2:
        left_player = players[0]
        right_player = players[1]

        left_health = snakes.get(left_player, {}).get("health", 0)
        right_health = snakes.get(right_player, {}).get("health", 0)

        left_x = geo["x"]
        right_x = geo["x"] + geo["pixel_width"] - HEALTH_BAR_WIDTH
        top_y = GRID_MARGIN - 5
        draw_corner_health_bar(screen, small_font, state["hud_name_font"], BLUE, state, left_x, top_y, left_player, left_health)
        draw_corner_health_bar(screen, small_font, state["hud_name_font"], ORANGE, state, right_x, top_y, right_player, right_health)

    time_seconds = int(match.get("remaining_seconds", 0))
    time_text = f"Time Left: {time_seconds}s"
    time_surface = font.render(time_text, True, WHITE)
    time_x = geo["x"] + (geo["pixel_width"] - time_surface.get_width()) // 2
    screen.blit(time_surface, (time_x, GRID_MARGIN + 6))

    draw_chat_panel(screen, match, state, small_font)

    pie_legend_y = geo["y"] + geo["pixel_height"] + 10
    draw_pie_descriptions(screen, small_font, geo["x"], pie_legend_y)

    controls_x = GRID_MARGIN
    controls_y = HEIGHT - 72
    if state["is_spectator"]:
        draw_text_line(screen, small_font, "Mode: Spectator", YELLOW, controls_x, controls_y)
    else:
        draw_text_line(screen, small_font, "Arrows: move snake", WHITE, controls_x, controls_y)
    draw_text_line(screen, small_font, "Esc: back to lobby", WHITE, controls_x, controls_y + 24)


#draws the game screen including board and contextual status text.
def draw_game_screen(screen, font, big_font, small_font, state):
    frame_bg = get_scaled_surface(state, "arena_frame_bg", state.get("game_ui_assets", {}).get("arena_frame_bg"), WIDTH, HEIGHT)
    if frame_bg is not None:
        screen.blit(frame_bg, (0, 0))
    else:
        screen.fill(BOARD_BG)
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
    pie_stats = game_over.get("pie_stats", {})

    winner_text = "Draw" if winner is None else f"Winner: {winner}"
    y = draw_text_line(screen, font, winner_text, YELLOW, 40, y + 20)
    y = draw_text_line(screen, font, f"Reason: {reason}", WHITE, 40, y)
    match = state.get("match") or {}
    players = match.get("players", [])
    for player_name in players:
        stats = pie_stats.get(player_name, {})
        pies_collected = stats.get("pies_collected", 0)
        high_score_label = stats.get("high_score_label", "high score: 0")
        y = draw_text_line(screen, font, f"{player_name} pies: {pies_collected} ({high_score_label})", WHITE, 40, y + 8)
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
    hud_name_font = pygame.font.SysFont("consolas", 30)

    state = create_client_state()
    state["menu_background"] = load_menu_background()
    state["game_ui_assets"] = load_game_ui_assets()
    state["hud_name_font"] = hud_name_font
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
