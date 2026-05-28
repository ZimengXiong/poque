from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import os
import re
import threading
from urllib.parse import parse_qs, urlparse

from game import PokerRoom


HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
MAX_BODY = 16 * 1024
ROOM = PokerRoom()
LOCK = threading.RLock()
SAFE_NAME = re.compile(r"[^a-zA-Z0-9 _.-]")
SAFE_ACTIONS = {"fold", "check", "call", "bet", "raise", "allin"}
BASE_DIR = os.path.dirname(__file__)


def sanitize_name(value: object) -> str:
    text = str(value or "player")[:80]
    text = SAFE_NAME.sub("", text).strip()
    return (text or "player")[:40]


def bounded_int(value: object, default: int = 0, minimum: int = 0, maximum: int = 1_000_000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def api_doc(base_url: str) -> dict:
    return {
        "name": "poque",
        "room_model": "single global room; all clients are trusted admins; no authentication",
        "base_url": base_url,
        "client_scripts": {
            "mvp": f"{base_url}/mvpclient.sh",
            "default": f"{base_url}/poque.sh",
        },
        "keepalive": "clients should POST /api/keepalive every 5 seconds; after 15 seconds they are disconnected and folded if in a hand",
        "server_authority": "server owns turn order, action validation, street advancement, showdown, and payout; clients only submit intent",
        "hand_evaluator": "showdown ranks are computed by the local C evaluator binary",
        "endpoints": [
            {"method": "GET", "path": "/api", "description": "this API document"},
            {"method": "GET", "path": "/api/state?player_id=<id>", "description": "room state; viewer sees own hole cards"},
            {"method": "POST", "path": "/api/join", "body": {"name": "string"}, "description": "join the room"},
            {"method": "POST", "path": "/api/keepalive", "body": {"player_id": "string"}, "description": "mark client connected"},
            {"method": "POST", "path": "/api/leave", "body": {"player_id": "string"}, "description": "leave; folds if hand is active"},
            {"method": "POST", "path": "/api/action", "body": {"player_id": "string", "action": "fold|check|call|bet|raise|allin", "amount": 100}, "description": "take turn action; amount is target total bet for bet/raise"},
            {"method": "POST", "path": "/api/admin/start", "body": {"small_blind": 10, "big_blind": 20, "starting_stack": 1000}, "description": "trusted admin start hand"},
            {"method": "POST", "path": "/api/admin/end", "body": {"reason": "string"}, "description": "trusted admin end hand"},
            {"method": "POST", "path": "/api/admin/restart", "body": {"small_blind": 10, "big_blind": 20, "starting_stack": 1000}, "description": "trusted admin end current hand and deal a new one"},
            {"method": "POST", "path": "/api/admin/reset", "body": {"reason": "string"}, "description": "trusted admin reset room, clear seats, and return to lobby"},
            {"method": "POST", "path": "/api/admin/backend/restart", "description": "trusted admin restart the backend process; Docker restarts the service"},
        ],
        "state_notes": {
            "to_act": "player_id that may act now; null outside betting rounds",
            "legal_actions": "included only for the viewer when ?player_id=<id> matches to_act",
            "cards": "viewer sees only their own hole cards until showdown",
            "pending": "players who must respond before the street can advance",
        },
        "cards": "rank+suit strings, ranks 2-9,T,J,Q,K,A and suits c,d,h,s",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "poque/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("cache-control", "no-store")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        length = bounded_int(self.headers.get("content-length"), default=0, maximum=MAX_BODY)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        base_url = f"https://{self.headers.get('x-forwarded-host') or self.headers.get('host') or 'poque.v3c.dev'}"
        try:
            if parsed.path in {"/", "/admin"}:
                self.send_text(admin_html(), "text/html; charset=utf-8")
            elif parsed.path in {"/api.md", "/API.md"}:
                with open(os.path.join(BASE_DIR, "API.md"), "r", encoding="utf-8") as doc:
                    self.send_text(doc.read(), "text/markdown; charset=utf-8")
            elif parsed.path in {"/api", "/api/"}:
                self.send_json(api_doc(base_url))
            elif parsed.path == "/api/state":
                viewer = str(query.get("player_id", [""])[0])[:64] or None
                with LOCK:
                    self.send_json({"ok": True, "state": ROOM.public_state(viewer)})
            elif parsed.path in {"/mvpclient.sh", "/poque.sh"}:
                self.send_text(client_script(base_url), "text/x-shellscript; charset=utf-8")
            else:
                self.send_json({"ok": False, "error": "not found"}, 404)
        except Exception as exc:
            error = str(exc)
            try:
                parsed_error = json.loads(error)
            except json.JSONDecodeError:
                parsed_error = None
            self.send_json({"ok": False, "error": error, "details": parsed_error}, 400)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            data = self.read_json()
            with LOCK:
                if parsed.path == "/api/join":
                    player = ROOM.join(sanitize_name(data.get("name")))
                    self.send_json({"ok": True, "player_id": player.id, "state": ROOM.public_state(player.id)})
                elif parsed.path == "/api/keepalive":
                    player_id = str(data.get("player_id", ""))[:64]
                    ROOM.keepalive(player_id)
                    self.send_json({"ok": True, "state": ROOM.public_state(player_id)})
                elif parsed.path == "/api/leave":
                    player_id = str(data.get("player_id", ""))[:64]
                    ROOM.leave(player_id)
                    self.send_json({"ok": True, "state": ROOM.public_state(player_id)})
                elif parsed.path == "/api/action":
                    player_id = str(data.get("player_id", ""))[:64]
                    action = str(data.get("action", "")).lower()[:16]
                    if action not in SAFE_ACTIONS:
                        raise ValueError("invalid action")
                    amount = bounded_int(data.get("amount"), default=0)
                    self.send_json({"ok": True, "state": ROOM.act(player_id, action, amount)})
                elif parsed.path == "/api/admin/start":
                    self.send_json(
                        {
                            "ok": True,
                            "state": ROOM.start(
                                small_blind=bounded_int(data.get("small_blind"), default=10, minimum=1),
                                big_blind=bounded_int(data.get("big_blind"), default=20, minimum=1),
                                starting_stack=bounded_int(data.get("starting_stack"), default=1000, minimum=1),
                            ),
                        }
                    )
                elif parsed.path == "/api/admin/end":
                    reason = sanitize_name(data.get("reason") or "admin ended hand")
                    self.send_json({"ok": True, "state": ROOM.end(reason)})
                elif parsed.path == "/api/admin/restart":
                    self.send_json(
                        {
                            "ok": True,
                            "state": ROOM.restart(
                                small_blind=bounded_int(data.get("small_blind"), default=10, minimum=1),
                                big_blind=bounded_int(data.get("big_blind"), default=20, minimum=1),
                                starting_stack=bounded_int(data.get("starting_stack"), default=1000, minimum=1),
                            ),
                        }
                    )
                elif parsed.path == "/api/admin/reset":
                    reason = sanitize_name(data.get("reason") or "admin reset room")
                    self.send_json({"ok": True, "state": ROOM.reset(reason)})
                elif parsed.path == "/api/admin/backend/restart":
                    self.send_json({"ok": True, "message": "backend restart scheduled"})
                    threading.Timer(0.25, lambda: os._exit(0)).start()
                else:
                    self.send_json({"ok": False, "error": "not found"}, 404)
        except Exception as exc:
            error = str(exc)
            try:
                parsed_error = json.loads(error)
            except json.JSONDecodeError:
                parsed_error = None
            self.send_json({"ok": False, "error": error, "details": parsed_error}, 400)


def client_script(base_url: str) -> str:
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail

BASE="${{POQUE_URL:-{base_url}}}"
NAME="${{1:-${{USER:-player}}}}"

need() {{ command -v "$1" >/dev/null 2>&1 || {{ echo "missing $1" >&2; exit 1; }}; }}
need curl
need python3

if [ -r /dev/tty ]; then
  exec 3</dev/tty
else
  echo "interactive mode needs a terminal; run: curl -fsSL $BASE/poque.sh -o poque.sh && bash poque.sh $NAME" >&2
  exit 1
fi

json_post() {{
  local path="$1" body="$2"
  curl -sS -H 'content-type: application/json' -X POST "$BASE$path" --data "$body"
}}

state_get() {{
  curl -sS "$BASE/api/state?player_id=$PLAYER_ID"
}}

api_or_error() {{
  local response
  response="$(json_post "$1" "$2")"
  printf '%s' "$response" | python3 -c '
import json, sys
data=json.load(sys.stdin)
if not data.get("ok"):
    print("error:", data.get("error", "unknown error"))
    raise SystemExit(1)
'
}}

JOIN="$(json_post /api/join "$(NAME="$NAME" python3 - <<PY
import json, os
print(json.dumps({{"name": os.environ.get("NAME", "player")}}))
PY
)")"
PLAYER_ID="$(printf '%s' "$JOIN" | python3 -c 'import json,sys; print(json.load(sys.stdin)["player_id"])')"
echo "joined poque as $NAME"
echo "player_id=$PLAYER_ID"

keepalive_loop() {{
  while :; do
    json_post /api/keepalive "{{\\"player_id\\":\\"$PLAYER_ID\\"}}" >/dev/null || true
    sleep 5
  done
}}
keepalive_loop &
KEEPALIVE_PID=$!
trap 'kill "$KEEPALIVE_PID" 2>/dev/null || true; json_post /api/leave "{{\\"player_id\\":\\"$PLAYER_ID\\"}}" >/dev/null || true' EXIT INT TERM

show_state() {{
  state_get | python3 -c '
import json, sys
data=json.load(sys.stdin)["state"]
print("\\nstage:", data["stage"], "pot:", data["pot"], "board:", " ".join(data["community"]) or "-")
print("to_act:", data["to_act"] or "-")
for p in data["players"]:
    mark="*" if p["id"] == data["to_act"] else " "
    cards=" ".join(p["cards"]) if p["cards"] else "-"
    print("{{}} seat {{}} {{}} stack={{}} bet={{}} connected={{}} folded={{}} cards={{}} id={{}}".format(mark, p["seat"], p["name"], p["stack"], p["bet"], p["connected"], p["folded"], cards, p["id"][:8]))
if data["events"]:
    print("last:", data["events"][-1]["message"])
'
}}

help_text() {{
  echo "commands:"
  echo "  state              refresh table"
  echo "  start              start a hand"
  echo "  end                end current hand"
  echo "  fold/check/call    act when it is your turn"
  echo "  bet N / raise N    set your total bet to N"
  echo "  allin              move all chips in"
  echo "  help               show this"
  echo "  leave              leave table"
}}

help_text
show_state
while printf '> ' > /dev/tty && read -r cmd arg <&3; do
  case "$cmd" in
    state|"") show_state ;;
    help) help_text ;;
    start) api_or_error /api/admin/start '{{}}' && show_state ;;
    end) api_or_error /api/admin/end '{{"reason":"cli end"}}' && show_state ;;
    fold|check|call|allin) api_or_error /api/action "{{\\"player_id\\":\\"$PLAYER_ID\\",\\"action\\":\\"$cmd\\"}}" && show_state ;;
    bet|raise) api_or_error /api/action "{{\\"player_id\\":\\"$PLAYER_ID\\",\\"action\\":\\"$cmd\\",\\"amount\\":${{arg:-0}}}}" && show_state ;;
    leave|quit|exit) exit 0 ;;
    *) echo "unknown command" ;;
  esac
done
"""


def admin_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Poque Developer Suite</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Fira+Code:wght@400;500;600&display=swap');

:root {
  --bg-primary: #070a09;
  --bg-secondary: #0f1412;
  --bg-table: radial-gradient(circle, #114a2f 0%, #062315 100%);
  --border-table: #3e2715;
  --gold: #d4af37;
  --gold-hover: #f1c40f;
  --gold-glow: rgba(212, 175, 55, 0.4);
  --green: #10b981;
  --blue: #2563eb;
  --red: #ef4444;
  --black: #1e293b;
  --text-primary: #f3f4f6;
  --text-secondary: #9ca3af;
  --font-family: 'Outfit', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: var(--font-family);
  background-color: var(--bg-primary);
  color: var(--text-primary);
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Custom Scrollbar */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.2);
}
::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}

header {
  background: var(--bg-secondary);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  z-index: 10;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.brand-section {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-logo {
  font-size: 24px;
  font-weight: 800;
  background: linear-gradient(135deg, var(--gold) 0%, #fff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: 1px;
}

.brand-badge {
  background: rgba(212, 175, 55, 0.1);
  border: 1px solid rgba(212, 175, 55, 0.3);
  color: var(--gold);
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 16px;
}

.toggle-container {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(0, 0, 0, 0.3);
  padding: 6px 12px;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #374151;
  transition: .3s;
  border-radius: 20px;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 14px;
  width: 14px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: .3s;
  border-radius: 50%;
}

input:checked + .toggle-slider {
  background-color: var(--gold);
}

input:checked + .toggle-slider:before {
  transform: translateX(16px);
}

.btn-shortcut {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
  font-family: var(--font-family);
  font-weight: 600;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}

.btn-shortcut:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.2);
}

.app-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
  height: calc(100vh - 60px);
}

.left-panel {
  flex: 3;
  display: flex;
  flex-direction: column;
  padding: 20px;
  overflow-y: auto;
  position: relative;
  background: radial-gradient(circle at center, #111614 0%, #080c0a 100%);
}

.right-panel {
  flex: 1;
  min-width: 340px;
  max-width: 420px;
  background: var(--bg-secondary);
  border-left: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Poker Table Layout */
.table-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 420px;
  position: relative;
}

.table-wrapper {
  position: relative;
  width: 100%;
  max-width: 820px;
  aspect-ratio: 2 / 1;
  margin: auto;
}

.table-felt {
  position: absolute;
  top: 10%;
  bottom: 10%;
  left: 10%;
  right: 10%;
  background: var(--bg-table);
  border: 15px solid var(--border-table);
  border-radius: 1000px;
  box-shadow: 
    inset 0 0 50px rgba(0,0,0,0.8),
    0 20px 40px rgba(0,0,0,0.7),
    0 0 0 1px rgba(255, 255, 255, 0.05);
  outline: 3px solid var(--gold);
  outline-offset: -15px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.felt-logo {
  position: absolute;
  top: 32%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 8px;
  color: rgba(212, 175, 55, 0.12);
  text-shadow: 1px 1px 1px rgba(255, 255, 255, 0.05);
  user-select: none;
  pointer-events: none;
  font-family: var(--font-family);
  text-transform: uppercase;
}

/* Community Cards */
.table-center {
  position: absolute;
  top: 55%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  z-index: 8;
}

.pot-display {
  background: rgba(0, 0, 0, 0.7);
  border: 1px solid rgba(212, 175, 55, 0.25);
  border-radius: 20px;
  padding: 4px 16px;
  font-weight: 600;
  color: #f1c40f;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 6px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.4);
}

.community-cards {
  display: flex;
  gap: 8px;
  height: 66px;
}

.community-card-slot {
  width: 46px;
  height: 66px;
  border: 2px dashed rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  background: rgba(0,0,0,0.2);
}

/* Seats Positioning */
.players-container {
  position: absolute;
  width: 100%;
  height: 100%;
  top: 0;
  left: 0;
  pointer-events: none;
}

.player-seat {
  position: absolute;
  width: 130px;
  display: flex;
  flex-direction: column;
  align-items: center;
  pointer-events: auto;
  z-index: 10;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.seat-box {
  width: 100%;
  background: rgba(15, 20, 18, 0.92);
  border: 2px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 6px 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(8px);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.seat-box.to-act {
  border-color: var(--green);
  box-shadow: 0 0 16px rgba(16, 185, 129, 0.5);
  animation: pulse-green 1.5s infinite alternate;
}

@keyframes pulse-green {
  from { box-shadow: 0 0 4px rgba(16, 185, 129, 0.2); }
  to { box-shadow: 0 0 16px rgba(16, 185, 129, 0.7); }
}

.seat-box.possessed {
  border-color: var(--gold);
  box-shadow: 0 0 16px rgba(212, 175, 55, 0.4);
}

.seat-box.folded {
  opacity: 0.4;
  filter: grayscale(0.5);
}

.seat-box.all-in {
  border-color: #f1c40f;
  animation: pulse-gold 1.2s infinite alternate;
}

@keyframes pulse-gold {
  from { box-shadow: 0 0 4px rgba(241, 196, 15, 0.2); }
  to { box-shadow: 0 0 16px rgba(241, 196, 15, 0.6); }
}

.seat-box.disconnected {
  border-color: #4b5563;
}

.seat-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1f2937 0%, #111827 100%);
  border: 1.5px solid rgba(255,255,255,0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  color: white;
  position: relative;
}

.avatar-letter {
  text-transform: uppercase;
}

.possess-indicator {
  position: absolute;
  bottom: -4px;
  right: -4px;
  background: var(--gold);
  border-radius: 50%;
  width: 14px;
  height: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

.seat-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.seat-name-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.conn-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.conn-online {
  background: var(--green);
  box-shadow: 0 0 4px var(--green);
}

.conn-offline {
  background: var(--red);
}

.seat-name {
  font-weight: 600;
  font-size: 13px;
  color: white;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.seat-stack {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  font-family: 'Fira Code', monospace;
}

.seat-badges {
  display: flex;
  gap: 3px;
  margin-top: 3px;
}

.seat-badge {
  font-size: 8px;
  font-weight: 800;
  padding: 1px 4px;
  border-radius: 3px;
  color: black;
  box-shadow: 0 1px 2px rgba(0,0,0,0.2);
  text-transform: uppercase;
}

.seat-badge.dealer { background: #f1c40f; }
.seat-badge.sb { background: #e67e22; color: white; }
.seat-badge.bb { background: #e74c3c; color: white; }

.seat-cards {
  display: flex;
  justify-content: center;
  gap: 3px;
  position: absolute;
  top: -22px;
  width: 100%;
  pointer-events: none;
}

/* Beautiful Cards */
.card {
  width: 32px;
  height: 46px;
  background: white;
  border-radius: 4px;
  box-shadow: 0 3px 6px rgba(0,0,0,0.4);
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 2px 3px;
  font-weight: 700;
  user-select: none;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s ease;
}

.card:hover {
  transform: translateY(-4px) scale(1.05);
  box-shadow: 0 6px 12px rgba(0,0,0,0.5);
  z-index: 10;
}

.card-back {
  background: radial-gradient(circle, #991b1b 0%, #450a0a 100%);
  border: 1.5px solid white;
}

.card-pattern {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255,255,255,0.12);
  font-size: 8px;
  letter-spacing: 0.5px;
}

.card-top {
  display: flex;
  flex-direction: column;
  line-height: 0.95;
  font-size: 10px;
  align-items: flex-start;
}

.card-center {
  font-size: 14px;
  align-self: center;
  margin-top: -2px;
}

.card-bottom {
  display: flex;
  flex-direction: column;
  line-height: 0.95;
  font-size: 10px;
  align-items: flex-end;
  transform: rotate(180deg);
}

.green-suit { color: var(--green); }
.blue-suit { color: var(--blue); }
.red-suit { color: var(--red); }
.black-suit { color: #111827; }

/* Interactive Overlays */
.seat-overlay-actions {
  position: absolute;
  bottom: -28px;
  display: flex;
  gap: 4px;
  opacity: 0;
  transform: translateY(-5px);
  transition: all 0.2s ease;
  pointer-events: none;
  z-index: 20;
}

.seat-box:hover .seat-overlay-actions {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

.seat-action-btn {
  background: var(--gold);
  color: black;
  border: none;
  font-family: var(--font-family);
  font-weight: 700;
  font-size: 9px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  text-transform: uppercase;
  box-shadow: 0 2px 4px rgba(0,0,0,0.3);
  transition: all 0.15s ease;
}

.seat-action-btn:hover {
  background: var(--gold-hover);
}

.seat-action-btn.possessed-badge {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-secondary);
  cursor: default;
}

.seat-kick-btn {
  background: #7f1d1d;
  color: white;
  border: none;
  font-size: 9px;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0,0,0,0.3);
  transition: all 0.15s ease;
}

.seat-kick-btn:hover {
  background: #b91c1c;
}

/* Active Bets Display */
.bets-container {
  position: absolute;
  width: 100%;
  height: 100%;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 7;
}

.bet-chip-capsule {
  position: absolute;
  background: rgba(0, 0, 0, 0.8);
  border: 1.2px solid rgba(212, 175, 55, 0.4);
  border-radius: 12px;
  padding: 2px 8px;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #f3f4f6;
  box-shadow: 0 2px 6px rgba(0,0,0,0.4);
  pointer-events: none;
  transition: all 0.3s ease;
}

.chip-icon {
  font-size: 10px;
}

/* Action Control HUD */
.action-panel-container {
  width: 100%;
  max-width: 820px;
  margin: 10px auto 0 auto;
  z-index: 10;
}

.action-panel {
  background: rgba(15, 20, 18, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 12px 20px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(10px);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.action-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  padding-bottom: 8px;
}

.possess-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.possess-status strong {
  color: var(--gold);
}

.status-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
}

.status-badge.red { background: rgba(239, 68, 68, 0.15); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.3); }
.status-badge.yellow { background: rgba(241, 196, 15, 0.15); color: #f1c40f; border: 1px solid rgba(241, 196, 15, 0.3); }

.btn-stop-possess {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
  font-family: var(--font-family);
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-stop-possess:hover {
  background: rgba(255, 255, 255, 0.1);
}

.action-buttons-wrapper {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.action-buttons {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
}

.btn-poker {
  font-family: var(--font-family);
  font-size: 13px;
  font-weight: 700;
  padding: 10px 18px;
  border-radius: 6px;
  cursor: pointer;
  border: none;
  transition: all 0.15s ease;
  min-width: 90px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  box-shadow: 0 3px 6px rgba(0,0,0,0.2);
}

.btn-poker:hover {
  transform: translateY(-1.5px);
  box-shadow: 0 5px 10px rgba(0,0,0,0.3);
}

.btn-poker:active {
  transform: translateY(0);
}

.btn-fold { background: #6b1d1d; color: #fca5a5; border: 1px solid #991b1b; }
.btn-fold:hover { background: #7f1d1d; }

.btn-check { background: #1e3a8a; color: #bfdbfe; border: 1px solid #2563eb; }
.btn-check:hover { background: #1d4ed8; }

.btn-call { background: #064e3b; color: #a7f3d0; border: 1px solid #059669; }
.btn-call:hover { background: #047857; }

.btn-raise { background: #78350f; color: #fde68a; border: 1px solid #d97706; }
.btn-raise:hover { background: #b45309; }

.btn-allin { 
  background: linear-gradient(135deg, #b45309 0%, #d97706 100%); 
  color: white; 
  border: 1px solid #f59e0b;
  animation: pulse-allin 1.5s infinite alternate;
}

@keyframes pulse-allin {
  from { box-shadow: 0 0 4px rgba(245, 158, 11, 0.4); }
  to { box-shadow: 0 0 12px rgba(245, 158, 11, 0.7); }
}

.raise-slider-container {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(0, 0, 0, 0.3);
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.raise-slider {
  flex: 1;
  accent-color: var(--gold);
  cursor: pointer;
  height: 4px;
}

.raise-amount-input {
  width: 75px;
  background: rgba(0,0,0,0.5);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  color: var(--gold);
  font-family: 'Fira Code', monospace;
  font-size: 13px;
  font-weight: 600;
  padding: 4px 6px;
  text-align: center;
}

.waiting-turn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.btn-quick-possess {
  background: rgba(212, 175, 55, 0.1);
  border: 1px solid rgba(212, 175, 55, 0.3);
  color: var(--gold);
  font-family: var(--font-family);
  font-weight: 600;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-left: 10px;
}

.btn-quick-possess:hover {
  background: rgba(212, 175, 55, 0.2);
}

.spinner-small {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-top-color: var(--gold);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.action-panel-placeholder {
  background: rgba(15, 20, 18, 0.5);
  border: 1px dashed rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 24px;
  text-align: center;
}

.placeholder-icon {
  font-size: 24px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.placeholder-text {
  font-weight: 600;
  font-size: 14px;
  color: white;
  margin-bottom: 4px;
}

.placeholder-sub {
  font-size: 12px;
  color: var(--text-secondary);
  max-width: 460px;
  margin: 0 auto;
}

/* Sidebar Panels */
.panel-section {
  padding: 18px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.panel-title {
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--gold);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.admin-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-row {
  display: flex;
  gap: 8px;
}

.form-group {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-group label {
  font-size: 10px;
  color: var(--text-secondary);
  text-transform: uppercase;
  font-weight: 600;
}

.form-group input {
  background: rgba(0,0,0,0.4);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  color: white;
  padding: 6px 10px;
  font-family: 'Fira Code', monospace;
  font-size: 12px;
  transition: all 0.2s ease;
}

.form-group input:focus {
  outline: none;
  border-color: var(--gold);
}

.btn-admin {
  background: var(--gold);
  color: black;
  font-family: var(--font-family);
  font-weight: 700;
  font-size: 13px;
  border: none;
  border-radius: 6px;
  padding: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-admin:hover {
  background: var(--gold-hover);
}

.btn-admin-danger {
  background: #5c1c1c;
  color: #fca5a5;
  border: 1px solid #7f1d1d;
  font-family: var(--font-family);
  font-weight: 600;
  font-size: 12px;
  border-radius: 6px;
  padding: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-admin-danger:hover {
  background: #7f1d1d;
}

/* Sidebar Spectator list */
.spectator-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 140px;
  overflow-y: auto;
}

.spectator-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(0, 0, 0, 0.2);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.spectator-name-col {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}

.spectator-actions {
  display: flex;
  gap: 4px;
}

.btn-mini-control {
  background: rgba(212, 175, 55, 0.1);
  border: 1px solid rgba(212, 175, 55, 0.3);
  color: var(--gold);
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  cursor: pointer;
}

.btn-mini-control:hover {
  background: rgba(212, 175, 55, 0.2);
}

/* Dealer Feed Chat */
.dealer-feed-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.15);
}

.feed-header {
  padding: 10px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.feed-title {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--text-secondary);
  letter-spacing: 0.5px;
}

.btn-clear-feed {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
}

.btn-clear-feed:hover {
  color: white;
}

.feed-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.event-item {
  display: flex;
  gap: 8px;
  font-size: 12px;
  line-height: 1.4;
  border-bottom: 1px solid rgba(255, 255, 255, 0.02);
  padding-bottom: 4px;
}

.event-icon {
  flex-shrink: 0;
}

.event-text {
  flex: 1;
}

.event-time {
  font-size: 10px;
  color: var(--text-secondary);
  font-family: 'Fira Code', monospace;
  align-self: flex-start;
}

.event-normal { color: var(--text-primary); }
.event-win { color: #f1c40f; font-weight: 600; }
.event-blind { color: var(--text-secondary); }
.event-bet { color: #60a5fa; }
.event-fold { color: #f87171; }
.event-check { color: #a7f3d0; }
.event-start { color: #fde68a; font-weight: 500; border-top: 1px solid rgba(212,175,55,0.1); border-bottom: 1px solid rgba(212,175,55,0.1); padding: 4px 0; }
.event-advance { color: #cbd5e1; font-weight: 500; }
.event-join { color: #34d399; }
.event-leave { color: #9ca3af; }

.empty-feed {
  color: var(--text-secondary);
  font-size: 12px;
  text-align: center;
  margin-top: 20px;
}
</style>
</head>
<body>

<header>
  <div class="brand-section">
    <div class="brand-logo">poque</div>
    <div class="brand-badge">Developer Suite</div>
  </div>
  
  <div class="header-controls">
    <div class="toggle-container">
      <span>🔊 Sounds</span>
      <label class="toggle-switch">
        <input type="checkbox" id="sound-toggle" checked onchange="toggleSound(this.checked)">
        <span class="toggle-slider"></span>
      </label>
    </div>
    
    <div class="toggle-container">
      <span>🎮 Auto-Control</span>
      <label class="toggle-switch">
        <input type="checkbox" id="auto-possess-toggle" checked onchange="toggleAutoPossess(this.checked)">
        <span class="toggle-slider"></span>
      </label>
    </div>
    
    <button class="btn-shortcut" onclick="addMockPlayer()">
      <span>➕ Add Mock Player</span>
    </button>
  </div>
</header>

<div class="app-layout">
  <div class="left-panel">
    <!-- Poker Table Felt Area -->
    <div class="table-area">
      <div class="table-wrapper">
        <!-- Felt background -->
        <div class="table-felt">
          <div class="felt-logo">Poque Elite</div>
        </div>
        
        <!-- Bets placed on the felt in front of each seat -->
        <div class="bets-container" id="table-bets-container"></div>
        
        <!-- Community Cards & Pot in center -->
        <div class="table-center">
          <div class="pot-display" id="pot-display-el">
            <span class="chip-icon">🪙</span>
            <span>Pot: $0</span>
          </div>
          
          <div class="community-cards" id="community-cards-el">
            <div class="community-card-slot"></div>
            <div class="community-card-slot"></div>
            <div class="community-card-slot"></div>
            <div class="community-card-slot"></div>
            <div class="community-card-slot"></div>
          </div>
        </div>
        
        <!-- Players Seats overlay -->
        <div class="players-container" id="players-seats-container"></div>
      </div>
    </div>
    
    <!-- Player turn Action Panel HUD -->
    <div class="action-panel-container" id="action-panel-container">
      <!-- Dynamic action panel -->
    </div>
  </div>
  
  <div class="right-panel">
    <!-- Hand Controls panel -->
    <div class="panel-section">
      <div class="panel-title">Hand Configurations</div>
      <div class="admin-form">
        <div class="form-row">
          <div class="form-group">
            <label for="sb-input">Small Blind</label>
            <input type="number" id="sb-input" value="10" min="1">
          </div>
          <div class="form-group">
            <label for="bb-input">Big Blind</label>
            <input type="number" id="bb-input" value="20" min="1">
          </div>
          <div class="form-group">
            <label for="stack-input">Stack size</label>
            <input type="number" id="stack-input" value="1000" min="10">
          </div>
        </div>
        
        <button class="btn-admin" onclick="startHand()" id="btn-deal-hand">Deal Next Hand</button>
        <button class="btn-admin" onclick="restartHand()" style="margin-top: 8px;">Restart Hand</button>
      </div>
    </div>
    
    <!-- Room State panel -->
    <div class="panel-section">
      <div class="panel-title">
        <span>Room Details</span>
        <span style="display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end;">
          <button class="btn-admin-danger" onclick="endHand()" style="padding: 2px 8px; font-size: 10px;">Force End Hand</button>
          <button class="btn-admin-danger" onclick="resetRoom()" style="padding: 2px 8px; font-size: 10px;">Full Reset</button>
          <button class="btn-admin-danger" onclick="restartBackend()" style="padding: 2px 8px; font-size: 10px;">Restart Backend</button>
        </span>
      </div>
      <div style="font-size: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; color: var(--text-secondary);">
        <div>Stage: <strong id="stage-val" style="color: white; text-transform: uppercase;">lobby</strong></div>
        <div>Hand ID: <strong id="hand-val" style="color: white;">-</strong></div>
        <div>Viewer ID: <strong id="viewer-val" style="color: white; font-family: 'Fira Code', monospace;">-</strong></div>
        <div>Turn Owner: <strong id="actor-val" style="color: white;">-</strong></div>
      </div>
    </div>
    
    <!-- Spectator / Seat List -->
    <div class="panel-section">
      <div class="panel-title">Player Connections</div>
      <div class="spectator-list" id="spectator-list-el">
        <!-- Dynamic list of players -->
      </div>
    </div>
    
    <!-- Real-time Event log (Dealer chat) -->
    <div class="dealer-feed-container">
      <div class="feed-header">
        <div class="feed-title">Dealer Ledger</div>
        <button class="btn-clear-feed" onclick="clearFeed()">Clear</button>
      </div>
      <div class="feed-list" id="feed-list-el">
        <!-- Real-time feed -->
      </div>
    </div>
  </div>
</div>

<script>
// Synthesizer Audio Engine
const PokerSounds = {
  ctx: null,
  enabled: true,

  init() {
    if (this.ctx) return;
    try {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    } catch (e) {
      console.warn("Web Audio API not supported", e);
    }
  },

  playShuffle() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    for (let i = 0; i < 4; i++) {
      const time = now + i * 0.07;
      this.noise(time, 0.04, 0.08);
    }
  },

  playChip() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    this.tone(now, 1600, 1800, 0.02, 0.12);
    this.tone(now + 0.03, 1400, 1500, 0.02, 0.08);
  },

  playCheck() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    this.tone(now, 220, 110, 0.08, 0.15, 'triangle');
  },

  playFold() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    this.noise(now, 0.12, 0.08, 800);
  },

  playAlert() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    this.tone(now, 784, 784, 0.06, 0.08, 'sine');
    this.tone(now + 0.08, 987, 987, 0.1, 0.08, 'sine');
  },

  playWin() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    const notes = [523.25, 659.25, 783.99, 1046.50];
    notes.forEach((freq, idx) => {
      this.tone(now + idx * 0.08, freq, freq, 0.16, 0.06, 'sine');
    });
  },

  tone(time, startFreq, endFreq, duration, volume, type = 'sine') {
    try {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      
      osc.type = type;
      osc.frequency.setValueAtTime(startFreq, time);
      osc.frequency.exponentialRampToValueAtTime(endFreq, time + duration);
      
      gain.gain.setValueAtTime(volume, time);
      gain.gain.exponentialRampToValueAtTime(0.0001, time + duration);
      
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      
      osc.start(time);
      osc.stop(time + duration);
    } catch(e){}
  },

  noise(time, duration, volume, frequencyCutoff = 2500) {
    try {
      const bufferSize = this.ctx.sampleRate * duration;
      const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) {
        data[i] = Math.random() * 2 - 1;
      }
      
      const noiseNode = this.ctx.createBufferSource();
      noiseNode.buffer = buffer;
      
      const filter = this.ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.frequency.setValueAtTime(frequencyCutoff, time);
      
      const gain = this.ctx.createGain();
      gain.gain.setValueAtTime(volume, time);
      gain.gain.exponentialRampToValueAtTime(0.0001, time + duration);
      
      noiseNode.connect(filter);
      filter.connect(gain);
      gain.connect(this.ctx.destination);
      
      noiseNode.start(time);
      noiseNode.stop(time + duration);
    } catch(e){}
  }
};

// Global App State
let possessedPlayerId = localStorage.getItem('possessedPlayerId') || '';
let autoPossess = localStorage.getItem('autoPossess') !== 'false';
let gameState = null;

// Initial setup
document.getElementById('sound-toggle').checked = PokerSounds.enabled;
document.getElementById('auto-possess-toggle').checked = autoPossess;

// Seat position layout mapping (for an 8-max ring game)
const seatPositions = {
  1: { x: 50, y: 0 },    // Top Center
  2: { x: 80, y: 15 },   // Top Right
  3: { x: 95, y: 50 },   // Middle Right
  4: { x: 80, y: 85 },   // Bottom Right
  5: { x: 50, y: 100 },  // Bottom Center
  6: { x: 20, y: 85 },   // Bottom Left
  7: { x: 5, y: 50 },    // Middle Left
  8: { x: 20, y: 15 }    // Top Left
};

// Active chip display layout coordinates
const betPositions = {
  1: { x: 50, y: 30 },
  2: { x: 72, y: 33 },
  3: { x: 77, y: 50 },
  4: { x: 72, y: 67 },
  5: { x: 50, y: 70 },
  6: { x: 28, y: 67 },
  7: { x: 23, y: 50 },
  8: { x: 28, y: 33 }
};

// Helper function to scan the next active player seat
function nextEligibleIndex(players, startIndex) {
  if (players.length === 0) return -1;
  for (let offset = 1; offset <= players.length; offset++) {
    const idx = (startIndex + offset) % players.length;
    const p = players[idx];
    if (p.connected && p.stack > 0) {
      return idx;
    }
  }
  return -1;
}

// Sound toggle controls
function toggleSound(checked) {
  PokerSounds.enabled = checked;
}

// Auto possess turn toggle controls
function toggleAutoPossess(checked) {
  autoPossess = checked;
  localStorage.setItem('autoPossess', checked);
  if (checked && gameState && gameState.to_act) {
    possessPlayer(gameState.to_act);
  }
}

// Play Turn or manually possess a player
function possessPlayer(id) {
  possessedPlayerId = id;
  localStorage.setItem('possessedPlayerId', id);
  refreshState();
}

function stopPossessing() {
  possessedPlayerId = '';
  localStorage.removeItem('possessedPlayerId');
  refreshState();
}

// Standard API fetcher
async function api(path, body){
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body || {})
  });
  return r.json();
}

// Kick player off the table
async function kickPlayer(id) {
  try {
    const res = await api('/api/leave', { player_id: id });
    if (res.ok) {
      if (possessedPlayerId === id) {
        stopPossessing();
      }
      refreshState();
    }
  } catch (e) {
    console.error("Error leaving", e);
  }
}

// Admin hand controllers
async function startHand() {
  const sb = parseInt(document.getElementById('sb-input').value, 10) || 10;
  const bb = parseInt(document.getElementById('bb-input').value, 10) || 20;
  const stack = parseInt(document.getElementById('stack-input').value, 10) || 1000;
  
  try {
    const res = await api('/api/admin/start', { small_blind: sb, big_blind: bb, starting_stack: stack });
    if (res.ok) {
      detectChanges(res.state);
      gameState = res.state;
      render(res.state);
    } else {
      alert("Cannot start: " + res.error);
    }
  } catch(e) {
    console.error(e);
  }
}

async function endHand() {
  try {
    const res = await api('/api/admin/end', { reason: "admin stopped hand" });
    if (res.ok) {
      detectChanges(res.state);
      gameState = res.state;
      render(res.state);
    }
  } catch(e) {
    console.error(e);
  }
}

async function restartHand() {
  const sb = parseInt(document.getElementById('sb-input').value, 10) || 10;
  const bb = parseInt(document.getElementById('bb-input').value, 10) || 20;
  const stack = parseInt(document.getElementById('stack-input').value, 10) || 1000;

  try {
    const res = await api('/api/admin/restart', { small_blind: sb, big_blind: bb, starting_stack: stack });
    if (res.ok) {
      detectChanges(res.state);
      gameState = res.state;
      render(res.state);
    } else {
      alert("Cannot restart hand: " + res.error);
    }
  } catch(e) {
    console.error(e);
  }
}

async function resetRoom() {
  if (!confirm("Full reset? This destroys all game state, kicks every player, clears all cards/chips/events, and returns to a blank lobby.")) return;
  try {
    const res = await api('/api/admin/reset', { reason: "admin reset room" });
    if (res.ok) {
      possessedPlayerId = '';
      localStorage.removeItem('possessedPlayerId');
      detectChanges(res.state);
      gameState = res.state;
      render(res.state);
    } else {
      alert("Cannot reset room: " + res.error);
    }
  } catch(e) {
    console.error(e);
  }
}

async function restartBackend() {
  if (!confirm("Restart the backend process? The table will be unavailable briefly.")) return;
  try {
    const res = await api('/api/admin/backend/restart', {});
    if (!res.ok) {
      alert("Cannot restart backend: " + res.error);
      return;
    }
    setTimeout(refreshState, 2500);
  } catch(e) {
    console.error(e);
  }
}

// Add Mock Player System
const botNames = [
  "Doyle Brunson", "Phil Ivey", "Daniel Negreanu", "Johnny Chan", 
  "Phil Hellmuth", "Vanessa Selbst", "Gus Hansen", "Chris Moneymaker"
];

async function addMockPlayer() {
  const currentNames = gameState ? gameState.players.map(p => p.name) : [];
  const available = botNames.filter(name => !currentNames.includes(name));
  const name = available.length > 0 
    ? available[Math.floor(Math.random() * available.length)] 
    : "Player " + (currentNames.length + 1);
    
  try {
    const res = await api('/api/join', { name });
    if (res.ok) {
      if (!possessedPlayerId) {
        possessPlayer(res.player_id);
      }
      PokerSounds.playShuffle();
      refreshState();
    }
  } catch (err) {
    console.error(err);
  }
}

// Render dynamic card designs
function renderCard(cardStr) {
  if (!cardStr || cardStr === '??') {
    return `<div class="card card-back"><div class="card-pattern">♠♥♦♣</div></div>`;
  }
  const rank = cardStr[0];
  const suitChar = cardStr[1];
  const suits = {
    'c': { symbol: '♣', name: 'clubs', color: 'green-suit' },
    'd': { symbol: '♦', name: 'diamonds', color: 'blue-suit' },
    'h': { symbol: '♥', name: 'hearts', color: 'red-suit' },
    's': { symbol: '♠', name: 'spades', color: 'black-suit' }
  };
  const suit = suits[suitChar] || { symbol: suitChar, name: '', color: '' };
  const displayRank = rank === 'T' ? '10' : rank;
  
  return `
    <div class="card ${suit.color}">
      <div class="card-top">
        <span class="card-rank">${displayRank}</span>
        <span class="card-suit" style="margin-top:-2px;">${suit.symbol}</span>
      </div>
      <div class="card-center">${suit.symbol}</div>
      <div class="card-bottom">
        <span class="card-suit" style="margin-top:-2px;">${suit.symbol}</span>
        <span class="card-rank">${displayRank}</span>
      </div>
    </div>
  `;
}

// HTML escape helper
function esc(v){
  return String(v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// Submit action on behalf of player
async function submitAction(action, amount) {
  if (!possessedPlayerId) return;
  const body = { player_id: possessedPlayerId, action };
  if (action === 'raise' && amount) {
    body.amount = parseInt(amount, 10);
  }
  
  try {
    const res = await api('/api/action', body);
    if (res.ok) {
      detectChanges(res.state);
      gameState = res.state;
      render(res.state);
    } else {
      alert("Action failed: " + res.error);
    }
  } catch (err) {
    console.error(err);
  }
}

// Sliders controls
function updateRaiseAmount(val) {
  document.getElementById('raise-amount-val').value = val;
}
function updateSlider(val) {
  const slider = document.getElementById('raise-slider-input');
  if (slider) {
    const v = parseInt(val, 10);
    if (v >= parseInt(slider.min) && v <= parseInt(slider.max)) {
      slider.value = v;
    }
  }
}

// Local ledger clear
function clearFeed() {
  document.getElementById('feed-list-el').innerHTML = `<div class="empty-feed">Ledger cleared</div>`;
}

// Render dynamic components
function render(s) {
  // Update details
  document.getElementById('stage-val').textContent = s.stage;
  document.getElementById('hand-val').textContent = s.hand_number || '-';
  document.getElementById('viewer-val').textContent = possessedPlayerId ? possessedPlayerId.slice(0, 8) : 'Spectator';
  
  const activeActor = s.players.find(p => p.id === s.to_act);
  document.getElementById('actor-val').textContent = activeActor ? activeActor.name : '-';
  
  // Deal config button toggle
  const eligibleCount = s.players.filter(p => p.connected && p.stack > 0).length;
  const btnDeal = document.getElementById('btn-deal-hand');
  if (s.stage !== 'lobby' && s.stage !== 'ended' && s.stage !== 'showdown') {
    btnDeal.textContent = "Hand in Progress";
    btnDeal.disabled = true;
    btnDeal.style.opacity = '0.5';
  } else {
    btnDeal.textContent = eligibleCount < 2 ? "Need 2+ Connected Players" : "Deal Next Hand";
    btnDeal.disabled = eligibleCount < 2;
    btnDeal.style.opacity = eligibleCount < 2 ? '0.5' : '1';
  }

  // Update Pot & Community Cards
  document.getElementById('pot-display-el').innerHTML = `<span class="chip-icon">🪙</span> Pot: $${s.pot.toLocaleString()}`;
  
  let communityHtml = '';
  for (let i = 0; i < 5; i++) {
    const card = s.community[i];
    if (card) {
      communityHtml += `<div class="community-card-slot" style="border:none;">${renderCard(card)}</div>`;
    } else {
      communityHtml += `<div class="community-card-slot"></div>`;
    }
  }
  document.getElementById('community-cards-el').innerHTML = communityHtml;

  // Render Players & Bets
  renderPlayersAndBets(s);

  // Render HUD Actions Panel
  renderHUD(s);

  // Render spectator list
  renderSpectatorList(s);

  // Render real-time logs feed
  renderLedger(s);
}

// Helper to position and render seats & bets on felt
function renderPlayersAndBets(s) {
  let seatsHtml = '';
  let betsHtml = '';

  let sbSeat = -1;
  let bbSeat = -1;
  
  if (s.dealer_seat !== null && s.players.length > 0) {
    const dealerIndex = s.players.findIndex(p => p.seat === s.dealer_seat);
    if (dealerIndex !== -1) {
      const eligiblePlayers = s.players.filter(p => p.connected && p.stack > 0);
      if (eligiblePlayers.length === 2) {
        sbSeat = s.dealer_seat;
        const bbIndex = nextEligibleIndex(s.players, dealerIndex);
        if (bbIndex !== -1) bbSeat = s.players[bbIndex].seat;
      } else if (eligiblePlayers.length > 2) {
        const sbIndex = nextEligibleIndex(s.players, dealerIndex);
        if (sbIndex !== -1) {
          sbSeat = s.players[sbIndex].seat;
          const bbIndex = nextEligibleIndex(s.players, sbIndex);
          if (bbIndex !== -1) bbSeat = s.players[bbIndex].seat;
        }
      }
    }
  }

  s.players.forEach(p => {
    const posIndex = ((p.seat - 1) % 8) + 1;
    const pos = seatPositions[posIndex];
    const betPos = betPositions[posIndex];

    const isToAct = p.id === s.to_act;
    const isPossessed = p.id === possessedPlayerId;

    let classes = 'seat-box';
    if (isToAct) classes += ' to-act';
    if (isPossessed) classes += ' possessed';
    if (p.folded) classes += ' folded';
    if (p.all_in) classes += ' all-in';
    if (!p.connected) classes += ' disconnected';

    const cardsHtml = p.cards.map(c => renderCard(c)).join('');

    let badges = '';
    if (p.seat === s.dealer_seat) badges += '<span class="seat-badge dealer">D</span>';
    if (p.seat === sbSeat) badges += '<span class="seat-badge sb">SB</span>';
    if (p.seat === bbSeat) badges += '<span class="seat-badge bb">BB</span>';

    const connPulse = p.connected 
      ? '<span class="conn-dot conn-online" title="Connected"></span>'
      : '<span class="conn-dot conn-offline" title="Offline / Disconnected"></span>';

    seatsHtml += `
      <div class="player-seat" style="left: ${pos.x}%; top: ${pos.y}%; transform: translate(-50%, -50%);">
        <div class="seat-cards">
          ${p.folded ? '' : cardsHtml}
        </div>
        <div class="${classes}">
          <div class="seat-avatar">
            <span class="avatar-letter">${esc(p.name[0] || 'P')}</span>
            ${isPossessed ? '<span class="possess-indicator" title="Controlling player">🎮</span>' : ''}
          </div>
          <div class="seat-info">
            <div class="seat-name-row">
              ${connPulse}
              <span class="seat-name" title="${esc(p.name)}">${esc(p.name)}</span>
            </div>
            <div class="seat-stack">$${p.stack.toLocaleString()}</div>
            <div class="seat-badges">${badges}</div>
          </div>
          <div class="seat-overlay-actions">
            ${isPossessed 
              ? `<button class="seat-action-btn possessed-badge" disabled>Controlling</button>`
              : `<button class="seat-action-btn" onclick="possessPlayer('${p.id}')">Control</button>`
            }
            <button class="seat-kick-btn" onclick="kickPlayer('${p.id}')" title="Force Leave">🚪</button>
          </div>
        </div>
      </div>
    `;

    if (p.bet > 0) {
      betsHtml += `
        <div class="bet-chip-capsule" style="left: ${betPos.x}%; top: ${betPos.y}%; transform: translate(-50%, -50%);">
          <span class="chip-icon">🪙</span>
          <span>$${p.bet}</span>
        </div>
      `;
    }
  });

  document.getElementById('players-seats-container').innerHTML = seatsHtml;
  document.getElementById('table-bets-container').innerHTML = betsHtml;
}

// Render control HUD at bottom
function renderHUD(s) {
  const hud = document.getElementById('action-panel-container');
  
  if (!possessedPlayerId) {
    hud.innerHTML = `
      <div class="action-panel-placeholder">
        <div class="placeholder-icon">🎮</div>
        <div class="placeholder-text">Lobby View Mode</div>
        <div class="placeholder-sub">Click <strong>"Control"</strong> on any player card above to act on their behalf, or toggle <strong>"Auto-Control"</strong> to auto-switch during turns.</div>
      </div>
    `;
    return;
  }

  const p = s.players.find(x => x.id === possessedPlayerId);
  if (!p) {
    // possessed player no longer exists
    possessedPlayerId = '';
    localStorage.removeItem('possessedPlayerId');
    renderHUD(s);
    return;
  }

  const isMyTurn = s.to_act === possessedPlayerId;
  const headerHtml = `
    <div class="action-header">
      <div class="possess-status">
        <span>🎮 Controlling: <strong>${esc(p.name)}</strong> ($${p.stack.toLocaleString()})</span>
        ${p.folded ? '<span class="status-badge red">Folded</span>' : ''}
        ${p.all_in ? '<span class="status-badge yellow">All-In</span>' : ''}
      </div>
      <button class="btn-stop-possess" onclick="stopPossessing()">Spectate 👁️</button>
    </div>
  `;

  if (!isMyTurn) {
    const curActor = s.players.find(x => x.id === s.to_act);
    hud.innerHTML = `
      <div class="action-panel">
        ${headerHtml}
        <div class="waiting-turn">
          <div class="spinner-small"></div>
          <span>Waiting for <strong>${curActor ? esc(curActor.name) : 'next player'}</strong>...</span>
          ${curActor ? `<button class="btn-quick-possess" onclick="possessPlayer('${curActor.id}')">Possess ${esc(curActor.name)} ⚡</button>` : ''}
        </div>
      </div>
    `;
    return;
  }

  // Active turn options
  const actions = s.legal_actions || [];
  const foldAct = actions.find(a => a.action === 'fold');
  const checkAct = actions.find(a => a.action === 'check');
  const callAct = actions.find(a => a.action === 'call');
  const raiseAct = actions.find(a => a.action === 'raise');
  const allinAct = actions.find(a => a.action === 'allin');

  let buttonsHtml = '';
  if (foldAct) {
    buttonsHtml += `<button class="btn-poker btn-fold" onclick="submitAction('fold')">Fold</button>`;
  }
  if (checkAct) {
    buttonsHtml += `<button class="btn-poker btn-check" onclick="submitAction('check')">Check</button>`;
  }
  if (callAct) {
    buttonsHtml += `<button class="btn-poker btn-call" onclick="submitAction('call')">Call $${callAct.amount}</button>`;
  }

  let raiseSliderHtml = '';
  if (raiseAct) {
    buttonsHtml += `<button class="btn-poker btn-raise" onclick="submitAction('raise', document.getElementById('raise-amount-val').value)">Raise</button>`;
    raiseSliderHtml = `
      <div class="raise-slider-container">
        <span>Min: $${raiseAct.min_amount}</span>
        <input type="range" class="raise-slider" id="raise-slider-input" min="${raiseAct.min_amount}" max="${raiseAct.max_amount}" value="${raiseAct.min_amount}" oninput="updateRaiseAmount(this.value)">
        <span>Max: $${raiseAct.max_amount}</span>
        <input type="number" class="raise-amount-input" id="raise-amount-val" min="${raiseAct.min_amount}" max="${raiseAct.max_amount}" value="${raiseAct.min_amount}" oninput="updateSlider(this.value)">
      </div>
    `;
  }

  if (allinAct) {
    buttonsHtml += `<button class="btn-poker btn-allin" onclick="submitAction('allin')">All-In $${allinAct.amount - p.bet}</button>`;
  }

  hud.innerHTML = `
    <div class="action-panel">
      ${headerHtml}
      <div class="action-buttons-wrapper">
        <div class="action-buttons">
          ${buttonsHtml}
        </div>
        ${raiseSliderHtml}
      </div>
    </div>
  `;
}

// Spectator listing in sidebar
function renderSpectatorList(s) {
  const container = document.getElementById('spectator-list-el');
  if (s.players.length === 0) {
    container.innerHTML = `<div style="font-size:12px; color:var(--text-secondary); text-align:center; padding:10px;">No players at table</div>`;
    return;
  }

  container.innerHTML = s.players.map(p => {
    const isPossessed = p.id === possessedPlayerId;
    const isToAct = p.id === s.to_act;
    const bullet = p.connected ? '<span class="conn-dot conn-online"></span>' : '<span class="conn-dot conn-offline"></span>';
    
    return `
      <div class="spectator-item" style="${isToAct ? 'border: 1px solid var(--green);' : ''}">
        <div class="spectator-name-col">
          ${bullet}
          <strong style="${isPossessed ? 'color:var(--gold);' : ''}">${esc(p.name)}</strong>
          <span style="font-size:10px; color:var(--text-secondary);">Seat ${p.seat}</span>
        </div>
        <div class="spectator-actions">
          <span style="font-family:'Fira Code',monospace; margin-right:8px; font-weight:600;">$${p.stack}</span>
          ${isPossessed 
            ? `<span style="font-size:11px; padding:2px; color:var(--gold);">🎮</span>`
            : `<button class="btn-mini-control" onclick="possessPlayer('${p.id}')">Control</button>`
          }
        </div>
      </div>
    `;
  }).join('');
}

// Render dynamic colored dealer feed Ledger
function renderLedger(s) {
  const container = document.getElementById('feed-list-el');
  if (!s.events || s.events.length === 0) {
    container.innerHTML = `<div class="empty-feed">Ledger is empty</div>`;
    return;
  }

  // Render reverse chronological events
  container.innerHTML = s.events.slice().reverse().map(e => {
    let msg = e.message;
    let icon = '📝';
    let className = 'event-normal';
    
    if (msg.includes('wins')) {
      icon = '🏆';
      className = 'event-win';
    } else if (msg.includes('blind')) {
      icon = '🪙';
      className = 'event-blind';
    } else if (msg.includes('bet') || msg.includes('raise') || msg.includes('all-in') || msg.includes('call') || msg.includes('posts')) {
      icon = '💰';
      className = 'event-bet';
    } else if (msg.includes('fold')) {
      icon = '❌';
      className = 'event-fold';
    } else if (msg.includes('check')) {
      icon = '🤝';
      className = 'event-check';
    } else if (msg.includes('started') || msg.includes('hand ')) {
      icon = '🃏';
      className = 'event-start';
    } else if (msg.includes('advanced to')) {
      icon = '🔄';
      className = 'event-advance';
    } else if (msg.includes('joined')) {
      icon = '👋';
      className = 'event-join';
    } else if (msg.includes('left') || msg.includes('timed out')) {
      icon = '🚪';
      className = 'event-leave';
    }
    
    const timeStr = new Date(e.at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    
    return `
      <div class="event-item ${className}">
        <span class="event-icon">${icon}</span>
        <span class="event-text">${esc(msg)}</span>
        <span class="event-time">${timeStr}</span>
      </div>
    `;
  }).join('');
}

// Synth Sound Trigger Engine
function detectChanges(nextState) {
  if (!gameState) return;
  
  if (nextState.stage !== gameState.stage) {
    if (nextState.stage === 'showdown') {
      PokerSounds.playWin();
    } else if (['preflop', 'flop', 'turn', 'river'].includes(nextState.stage)) {
      PokerSounds.playShuffle();
    }
  } else if (nextState.community.length > gameState.community.length) {
    PokerSounds.playShuffle();
  }
  
  if (nextState.to_act && nextState.to_act !== gameState.to_act) {
    PokerSounds.playAlert();
  }
  
  nextState.players.forEach(nextP => {
    const prevP = gameState.players.find(x => x.id === nextP.id);
    if (prevP) {
      if (nextP.folded && !prevP.folded) {
        PokerSounds.playFold();
      }
      if (nextP.bet > prevP.bet) {
        PokerSounds.playChip();
      }
    }
  });
}

// Active State Loader
async function refreshState() {
  try {
    let url = '/api/state';
    
    // Auto possess checks
    if (autoPossess) {
      const basicRes = await fetch('/api/state');
      if (basicRes.ok) {
        const basicData = await basicRes.json();
        if (basicData.ok && basicData.state.to_act) {
          if (possessedPlayerId !== basicData.state.to_act) {
            possessedPlayerId = basicData.state.to_act;
            localStorage.setItem('possessedPlayerId', possessedPlayerId);
          }
        }
      }
    }
    
    if (possessedPlayerId) {
      url += '?player_id=' + encodeURIComponent(possessedPlayerId);
    }
    
    const r = await fetch(url);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    if (data.ok) {
      detectChanges(data.state);
      gameState = data.state;
      render(data.state);
    }
  } catch (err) {
    console.error("Refresh error:", err);
  }
}

// Keepalive broadcaster for ALL connected players
async function sendAllKeepalives() {
  if (!gameState || !gameState.players) return;
  for (const p of gameState.players) {
    if (p.connected) {
      try {
        fetch('/api/keepalive', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ player_id: p.id })
        });
      } catch (e) {}
    }
  }
}

// Timers
setInterval(refreshState, 1500);
setInterval(sendAllKeepalives, 4500);

// Run initial loading
refreshState();
</script>
</body>
</html>"""


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"poque listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
