# poque Backend and API Structure

`poque` is a frontend-agnostic, single-room Texas Hold'em server.

## Architecture

- `main.py`: HTTP boundary. Serves JSON API endpoints, `/admin`, `/poque.sh`, `/mvpclient.sh`, and this Markdown document.
- `game.py`: Authoritative room/game engine. Tracks seats, connections, keepalives, turn order, legal actions, street advancement, showdown, and side-pot payout.
- `evaluator.c` / `evaluator`: C hand evaluator invoked by the server at showdown. Python does not rank hands itself.
- Caddy: routes `https://poque.v3c.dev` to the `poque` container.

## Authority Model

The server is the only source of truth.

- Clients do not decide whose turn it is.
- Clients do not advance streets.
- Clients do not calculate winners or payouts.
- Clients only join, keep alive, leave, and submit intended actions.
- `/api/action` rejects actions from any player other than `state.to_act`.

## Connection Model

- One global room.
- One hand at a time.
- Clients join with `POST /api/join`.
- Clients should send `POST /api/keepalive` every 5 seconds.
- The server marks clients disconnected after 15 seconds without keepalive.
- If a player disconnects or leaves during a live hand, the server folds them.
- All clients are trusted admins for now. There is no auth.

## State Shape

`GET /api/state?player_id=<id>` returns:

```json
{
  "ok": true,
  "state": {
    "room": "main",
    "stage": "lobby|preflop|flop|turn|river|showdown",
    "hand_number": 1,
    "dealer_seat": 1,
    "small_blind": 10,
    "big_blind": 20,
    "pot": 30,
    "current_bet": 20,
    "to_act": "player_id_or_null",
    "pending": ["player_id"],
    "community": ["Ah", "Kd", "7c"],
    "players": [],
    "winners": [],
    "events": [],
    "limits": {
      "keepalive_interval_seconds": 5,
      "keepalive_timeout_seconds": 15,
      "min_players": 2,
      "max_body_bytes": 16384
    },
    "legal_actions": []
  }
}
```

Hole cards are hidden from other players until showdown. Supplying `player_id` reveals only that viewer's cards.

## Endpoints

### API Doc

```http
GET /api
```

Returns machine-readable endpoint metadata.

### State

```http
GET /api/state?player_id=<id>
```

Returns current room state. `player_id` is optional but needed to see your own hole cards and legal actions.

### Join

```http
POST /api/join
Content-Type: application/json

{"name":"Alice"}
```

Returns:

```json
{"ok":true,"player_id":"...","state":{}}
```

### Keepalive

```http
POST /api/keepalive
Content-Type: application/json

{"player_id":"..."}
```

Send every 5 seconds.

### Leave

```http
POST /api/leave
Content-Type: application/json

{"player_id":"..."}
```

Disconnects the player and folds them if a hand is live.

### Act

```http
POST /api/action
Content-Type: application/json

{"player_id":"...","action":"fold|check|call|bet|raise|allin","amount":100}
```

`amount` is the target total bet for `bet` and `raise`.

### Start Hand

```http
POST /api/admin/start
Content-Type: application/json

{"small_blind":10,"big_blind":20,"starting_stack":1000}
```

Starts a new hand. Requires at least two connected players with chips.

### End Hand

```http
POST /api/admin/end
Content-Type: application/json

{"reason":"admin ended hand"}
```

Ends the current hand and returns to lobby.

## Clients

```sh
curl -fsSL https://poque.v3c.dev/mvpclient.sh | bash -s Alice
```

Admin UI:

```text
https://poque.v3c.dev/admin
```
