# Backend Basic Demo

This backend now supports the full core demo flow:
- TCP server with one thread per client.
- Newline-delimited JSON protocol (`type`, `payload`).
- `LOGIN` with unique username validation.
- Lobby state (`online_users`, `waiting_players`, `spectators`).
- Matchmaking via `CHALLENGE_PLAYER` and `CHALLENGE_ACCEPT`.
- One authoritative active match managed by the server tick loop.
- Server-side snake movement, pie healing, obstacle/wall/body collision damage.
- Timer-based and health-based winner resolution.
- Broadcast of `MATCH_START`, `STATE_UPDATE`, and `GAME_OVER`.
- Disconnect handling that ends the match with `player_disconnected`.

## Run

From repository root:

```bash
python3 -m backend.server --host 0.0.0.0 --port 5000
```

## Core message flow

1. Client sends `LOGIN`.
2. Player A sends `CHALLENGE_PLAYER` with target username.
3. Player B receives `CHALLENGE_RECEIVED` and replies with `CHALLENGE_ACCEPT`.
4. Both players receive `MATCH_START`.
5. Players send `INPUT` messages with `direction` in `UP|DOWN|LEFT|RIGHT`.
6. Server broadcasts periodic `STATE_UPDATE`.
7. Server broadcasts `GAME_OVER` when match ends.

## Message examples

```json
{"type":"LOGIN","payload":{"username":"Ali"}}
```

```json
{"type":"CHALLENGE_PLAYER","payload":{"target":"Maya"}}
```

```json
{"type":"CHALLENGE_ACCEPT","payload":{"from":"Ali"}}
```

```json
{"type":"INPUT","payload":{"direction":"UP"}}
```

All messages must end with a newline (`\n`).
