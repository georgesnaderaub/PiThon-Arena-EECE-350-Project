# AGENTS

## Project Context
This repository implements a two-player snake arena game for EECE 350.
Use the plan in `ΠThon Arena Chat Plan.txt` as the source of truth for architecture and scope.

## System Design (Required)
- Use an authoritative centralized game server.
- Use TCP sockets with JSON message envelopes.
- Keep game state, rules, collisions, health, and winner logic on the server.
- Treat clients as input + rendering only.
- Keep chat as a separate peer-to-peer TCP channel between the two active players.

## Core Components
- Server: connection handling, lobby/matchmaking, game loop, state broadcast.
- Client: Pygame UI/screens, input capture, state rendering.
- Networking: framed JSON protocol (`type` + `payload`).
- Spectator mode: read-only state stream + cheer events.
- P2P chat: direct socket after server shares peer info.

## Suggested Message Types
- `LOGIN`, `LOGIN_OK`, `LOGIN_REJECT`
- `ONLINE_USERS`, `CHALLENGE_PLAYER`, `CHALLENGE_ACCEPT`, `WAITING`
- `MATCH_START`, `INPUT`, `STATE_UPDATE`, `GAME_OVER`
- `WATCH_MATCH`, `CHEER`, `PLAYER_DISCONNECTED`, `ERROR`
- `CHAT_PEER_INFO` (for P2P chat bootstrap)

## Server Loop Rules
At each tick:
1. Consume queued player inputs.
2. Validate movement constraints.
3. Move snakes.
4. Resolve pie pickups and health updates.
5. Resolve collisions (wall/obstacle/self/enemy/head-on).
6. Spawn or refresh pies as needed.
7. Update timer and check end conditions.
8. Broadcast authoritative `STATE_UPDATE` to players and spectators.

## Concurrency Model
- Server: accept thread + one thread per client + match loop thread.
- Client: Pygame main thread + network receive thread (+ optional chat thread).
- Use thread-safe queues/shared state boundaries.

## Gameplay Targets
- Two active players, equal starting health.
- Grid movement, fixed obstacles, multiple pie types.
- Match ends on zero health or timer expiry.
- If timer expires, higher health wins.

## Frontend Scope
- Connect screen (IP/port)
- Username screen
- Lobby (online list, challenge/wait, watch)
- Snake customization
- Game screen (board, snakes, pies, obstacles, health, timer)
- Game-over screen

## Creative Feature Recommendation
Primary recommendation: **Replay + match timeline** based on server snapshots/events.

## Delivery Priority
1. Login + unique username.
2. Lobby + player list + challenge/wait flow.
3. Authoritative server tick loop.
4. Movement + state broadcast.
5. Pies/obstacles/health/collisions/timer.
6. End-game + winner.
7. Spectator mode.
8. P2P chat.
9. Creative feature.
10. Fault handling and polish.

## Agent Working Rules
- Preserve authoritative server ownership of game state.
- Do not introduce client-side winner/game-truth decisions.
- Keep protocol changes explicit and documented.
- Prefer small, testable increments aligned to delivery priority.
- If requirements conflict, prioritize centralized game correctness over visual polish.
