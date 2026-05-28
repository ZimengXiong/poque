# poque

Frontend-agnostic single-room Texas Hold'em server.

Public endpoints:

- `https://poque.v3c.dev/api`
- `https://poque.v3c.dev/admin`
- `https://poque.v3c.dev/mvpclient.sh`
- `https://poque.v3c.dev/poque.sh`
- `https://client.v3c.dev`

## Web client

The React/Vite browser client lives in `client-web/`. It includes:

- `src/`: frontend table UI.
- `server.cjs`: small Node server that serves the built client, proxies `/api/*` to `poque.v3c.dev`, and keeps browser session mappings under `data/sessions.json`.
- `compose.yaml`: service definition for the live `poque-client` container.

The live route is configured outside this repo in the v3c Caddy config:

```text
client.v3c.dev -> poque-client:3000
```

## API

All clients are trusted admins. There is no authentication. Inputs are bounded and sanitized at the HTTP layer.
The server is authoritative: clients do not compute turn order, street changes, showdown, or payouts.

- `GET /api`: API document.
- `GET /api/state?player_id=<id>`: room state. The viewer sees only their own hole cards until showdown/end.
- `POST /api/join` with `{"name":"Alice"}`: joins the single room and returns `player_id`.
- `POST /api/keepalive` with `{"player_id":"..."}`: clients should send every 5 seconds.
- `POST /api/leave` with `{"player_id":"..."}`: disconnects the client and folds them if a hand is live.
- `POST /api/action` with `{"player_id":"...","action":"fold|check|call|bet|raise|allin","amount":100}`: submits a turn action. `amount` is the target total bet for `bet` and `raise`.
- `POST /api/admin/start` with `{"small_blind":10,"big_blind":20,"starting_stack":1000}`: starts one hand in the single room.
- `POST /api/admin/end` with `{"reason":"..."}`: ends the current hand/game.

Connection behavior:

- Keepalive interval: 5 seconds.
- Timeout: 15 seconds.
- Timed-out or explicitly leaving clients are marked disconnected.
- If disconnected during a live hand, the client is automatically folded.

Game behavior:

- One global room and one hand at a time.
- Seats are assigned by join order.
- Dealer rotates among connected players with chips.
- The server tracks `to_act`, `pending`, legal actions, street advancement, and showdown.
- Side pots are awarded at showdown based on each player's committed chips.
- Showdown hand ranking is delegated to the local C evaluator binary.

Run locally:

```sh
PORT=8765 python3 main.py
```

Build the C evaluator locally:

```sh
gcc -O3 -static -Wall -Wextra -o evaluator evaluator.c
```
