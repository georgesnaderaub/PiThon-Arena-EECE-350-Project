# Frontend Basic Demo

This frontend follows the tutorial coding style:
- Script-like Pygame loop (`init`, event loop, draw, update, `clock.tick`).
- Separate network listener thread so rendering never blocks.
- TCP + newline-delimited JSON messaging with the backend protocol.

## Screens implemented
- Connect screen (IP/port)
- Username screen
- Lobby screen (online users, challenge, accept, wait, watch)
- Game screen (render server state only)
- Game over screen

## Controls
- Connect screen: `Tab` switch field, `Enter` connect
- Username screen: type username + `Enter`
- Lobby: `Up/Down` select user, `C` challenge, `A` accept challenge, `W` wait, `V` watch
- Game: Arrow keys send movement (`INPUT`) for active player
- Game over: `L` return to lobby

## Run
From repository root:

```bash
python3 -m frontend.client
```

Start backend first:

```bash
python3 -m backend.server --host 0.0.0.0 --port 5000
```
