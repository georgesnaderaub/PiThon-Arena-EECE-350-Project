# Backend Connection Layer

This backend currently implements the connection/lobby foundation:
- TCP server with one thread per client.
- Newline-delimited JSON protocol (`type`, `payload`).
- `LOGIN` with unique username enforcement.
- Presence tracking for `online_users`, `waiting_players`, and `spectators`.
- Basic handling for `WAITING` and `WATCH_MATCH`.
- Broadcast of `ONLINE_USERS` whenever users join/leave.

## Run

From repository root:

```bash
python3 -m backend.server --host 0.0.0.0 --port 5000
```

## Message examples

Client login:

```json
{"type":"LOGIN","payload":{"username":"Ali"}}
```

Set waiting state:

```json
{"type":"WAITING","payload":{}}
```

Become spectator:

```json
{"type":"WATCH_MATCH","payload":{}}
```

All messages must end with a newline (`\n`).
