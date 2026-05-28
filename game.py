from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import random
import subprocess
import time
import uuid


RANKS = "23456789TJQKA"
SUITS = "cdhs"
KEEPALIVE_TIMEOUT = 15
EVALUATOR = Path(__file__).with_name("evaluator")


def ts() -> float:
    return time.time()


def card_text(card: int) -> str:
    return RANKS[card % 13] + SUITS[card // 13]


def json_like(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def hand_rank(cards: list[int]) -> tuple[int, str]:
    if len(cards) != 7:
        raise ValueError("hand evaluator requires seven cards")
    if not EVALUATOR.exists():
        raise RuntimeError("missing C hand evaluator binary")
    result = subprocess.run(
        [str(EVALUATOR), *[card_text(card) for card in cards]],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )
    score, name = result.stdout.strip().split("\t", 1)
    return int(score), name


@dataclass
class Player:
    id: str
    name: str
    seat: int
    stack: int = 1000
    connected: bool = True
    last_seen: float = field(default_factory=ts)
    cards: list[int] = field(default_factory=list)
    bet: int = 0
    invested: int = 0
    folded: bool = False
    all_in: bool = False


class PokerRoom:
    def __init__(self) -> None:
        self.players: list[Player] = []
        self.stage = "lobby"
        self.hand_number = 0
        self.dealer = -1
        self.small_blind = 10
        self.big_blind = 20
        self.deck: list[int] = []
        self.community: list[int] = []
        self.pot = 0
        self.current_bet = 0
        self.to_act: str | None = None
        self.pending: set[str] = set()
        self.winners: list[dict] = []
        self.events: list[dict] = []
        self.last_error: str | None = None

    def event(self, message: str) -> None:
        self.events.append({"at": round(ts(), 3), "message": message})
        self.events = self.events[-100:]

    def join(self, name: str) -> Player:
        self.prune()
        player = Player(id=uuid.uuid4().hex[:16], name=name, seat=len(self.players) + 1)
        if self.stage != "lobby":
            player.folded = True
        self.players.append(player)
        if player.folded:
            self.event(f"{player.name} joined seat {player.seat} and is waiting for the next hand")
        else:
            self.event(f"{player.name} joined seat {player.seat}")
        return player

    def keepalive(self, player_id: str) -> None:
        player = self.get_player(player_id)
        player.connected = True
        player.last_seen = ts()

    def leave(self, player_id: str) -> dict:
        player = self.get_player(player_id)
        player.connected = False
        player.last_seen = 0
        if self.live_hand() and not player.folded:
            self.fold_player(player)
            self.after_action()
        self.event(f"{player.name} left")
        return self.public_state(player_id)

    def start(self, small_blind: int = 10, big_blind: int = 20, starting_stack: int = 1000) -> dict:
        self.prune()
        eligible = [p for p in self.players if p.connected and p.stack > 0]
        if len(eligible) < 2:
            raise ValueError("need at least two connected players")
        self.small_blind = small_blind
        self.big_blind = max(big_blind, small_blind)
        for p in self.players:
            if p.stack <= 0:
                p.stack = starting_stack
        self.hand_number += 1
        self.stage = "preflop"
        self.deck = list(range(52))
        random.shuffle(self.deck)
        self.community = []
        self.pot = 0
        self.current_bet = 0
        self.pending = set()
        self.winners = []
        self.last_error = None
        self.dealer = self.next_eligible_index(self.dealer)
        for p in self.players:
            p.cards = []
            p.bet = 0
            p.invested = 0
            p.folded = not (p.connected and p.stack > 0)
            p.all_in = False
            if not p.folded:
                p.cards = [self.deck.pop(), self.deck.pop()]
        active_count = len([p for p in self.players if not p.folded])
        if active_count == 2:
            sb_i = self.dealer
            bb_i = self.next_eligible_index(sb_i)
        else:
            sb_i = self.next_eligible_index(self.dealer)
            bb_i = self.next_eligible_index(sb_i)
        self.commit(self.players[sb_i], self.small_blind)
        self.event(f"{self.players[sb_i].name} posts small blind {self.players[sb_i].bet}")
        self.commit(self.players[bb_i], self.big_blind)
        self.event(f"{self.players[bb_i].name} posts big blind {self.players[bb_i].bet}")
        self.current_bet = max(p.bet for p in self.active_players())
        self.pending = {p.id for p in self.actionable_players() if p.bet < self.current_bet}
        first = self.next_actionable_index(bb_i)
        self.to_act = self.players[first].id if first is not None else None
        if self.to_act:
            self.pending.add(self.to_act)
        self.event(f"hand {self.hand_number} started")
        self.after_action()
        return self.public_state()

    def end(self, reason: str = "game ended") -> dict:
        if self.live_hand():
            while len(self.community) < 5:
                self.community.append(self.deck.pop())
            live = self.active_players()
            if len(live) == 1:
                self.award(live, "admin ended hand")
            elif len(live) > 1:
                self.showdown()
            else:
                self.stage = "ended"
                self.to_act = None
                self.pending = set()
        else:
            self.stage = "lobby"
            self.to_act = None
            self.pending = set()
        self.event(reason)
        return self.public_state()

    def restart(self, small_blind: int = 10, big_blind: int = 20, starting_stack: int = 1000) -> dict:
        if self.live_hand():
            self.stage = "lobby"
            self.to_act = None
            self.pending = set()
            self.pot = 0
            self.current_bet = 0
            self.community = []
            self.winners = []
            for player in self.players:
                player.cards = []
                player.bet = 0
                player.invested = 0
                player.folded = False
                player.all_in = False
            self.event("admin discarded current hand")
        return self.start(small_blind=small_blind, big_blind=big_blind, starting_stack=starting_stack)

    def reset(self, reason: str = "admin reset room") -> dict:
        self.players = []
        self.stage = "lobby"
        self.hand_number = 0
        self.dealer = -1
        self.deck = []
        self.community = []
        self.pot = 0
        self.current_bet = 0
        self.to_act = None
        self.pending = set()
        self.winners = []
        self.events = []
        self.last_error = None
        self.event(reason)
        return self.public_state()

    def act(self, player_id: str, action: str, amount: int = 0) -> dict:
        self.prune()
        if not self.live_hand():
            self.fail_action(player_id, action, "no active betting round", stage=self.stage)
        if player_id != self.to_act:
            self.fail_action(
                player_id,
                action,
                "not your turn; server controls turn order",
                stage=self.stage,
                to_act=self.to_act,
                requested_by=player_id,
            )
        player = self.get_player(player_id)
        if player.folded:
            self.fail_action(player_id, action, "player cannot act because they are folded", player=self.debug_player(player))
        if player.all_in:
            self.fail_action(player_id, action, "player cannot act because they are all-in", player=self.debug_player(player))
        if not player.connected:
            self.fail_action(player_id, action, "player cannot act because they are disconnected", player=self.debug_player(player))
        action = "raise" if action == "bet" else action
        to_call = self.current_bet - player.bet
        if action == "fold":
            self.fold_player(player)
        elif action == "check":
            if to_call:
                self.fail_action(player_id, action, "cannot check; call, raise, or fold", to_call=to_call, current_bet=self.current_bet, player_bet=player.bet)
        elif action == "call":
            self.commit(player, to_call)
        elif action == "allin":
            target = player.bet + player.stack
            self.commit(player, player.stack)
            if target > self.current_bet:
                self.current_bet = target
                self.pending = {p.id for p in self.actionable_players() if p.id != player.id}
        elif action == "raise":
            if amount <= self.current_bet:
                self.fail_action(player_id, action, "raise amount must be a target total above current bet", amount=amount, current_bet=self.current_bet)
            if amount - player.bet <= 0:
                self.fail_action(player_id, action, "raise amount is already covered", amount=amount, player_bet=player.bet)
            self.commit(player, amount - player.bet)
            self.current_bet = player.bet
            self.pending = {p.id for p in self.actionable_players() if p.id != player.id}
        else:
            self.fail_action(player_id, action, "invalid action")
        self.pending.discard(player.id)
        self.event(f"{player.name} {action}{f' to {amount}' if action == 'raise' else ''}")
        self.after_action()
        return self.public_state(player_id)

    def fail_action(self, player_id: str, action: str, reason: str, **details: object) -> None:
        payload = {
            "reason": reason,
            "player_id": player_id,
            "action": action,
            "stage": self.stage,
            "to_act": self.to_act,
            "pending": sorted(self.pending),
            **details,
        }
        self.last_error = reason
        self.event(f"action rejected: {reason}; details={payload}")
        raise ValueError(json_like(payload))

    def debug_player(self, player: Player) -> dict:
        return {
            "id": player.id,
            "name": player.name,
            "seat": player.seat,
            "connected": player.connected,
            "folded": player.folded,
            "all_in": player.all_in,
            "stack": player.stack,
            "bet": player.bet,
            "invested": player.invested,
        }

    def public_state(self, viewer_id: str | None = None) -> dict:
        self.prune()
        return {
            "room": "main",
            "keepalive_seconds": 5,
            "timeout_seconds": KEEPALIVE_TIMEOUT,
            "stage": self.stage,
            "hand_number": self.hand_number,
            "dealer_seat": self.players[self.dealer].seat if 0 <= self.dealer < len(self.players) else None,
            "small_blind": self.small_blind,
            "big_blind": self.big_blind,
            "pot": self.pot,
            "current_bet": self.current_bet,
            "to_act": self.to_act,
            "pending": sorted(self.pending),
            "community": [card_text(c) for c in self.community],
            "players": [self.player_state(p, viewer_id) for p in self.players],
            "winners": self.winners,
            "events": self.events,
            "limits": {
                "keepalive_interval_seconds": 5,
                "keepalive_timeout_seconds": KEEPALIVE_TIMEOUT,
                "min_players": 2,
                "max_body_bytes": 16384,
            },
            "legal_actions": self.legal_actions(viewer_id),
            "last_error": self.last_error,
        }

    def player_state(self, player: Player, viewer_id: str | None) -> dict:
        reveal = player.id == viewer_id or self.stage == "showdown"
        return {
            "id": player.id,
            "name": player.name,
            "seat": player.seat,
            "stack": player.stack,
            "connected": player.connected,
            "last_seen_age": round(ts() - player.last_seen, 1),
            "cards": [card_text(c) for c in player.cards] if reveal else ["??"] * len(player.cards),
            "bet": player.bet,
            "invested": player.invested,
            "folded": player.folded,
            "all_in": player.all_in,
        }

    def prune(self) -> None:
        if getattr(self, "_pruning", False):
            return
        self._pruning = True
        try:
            cutoff = ts() - KEEPALIVE_TIMEOUT
            changed = False
            for p in self.players:
                if p.connected and p.last_seen < cutoff:
                    p.connected = False
                    self.event(f"{p.name} timed out")
                    if self.live_hand() and not p.folded:
                        self.fold_player(p)
                        changed = True
            if changed:
                self.after_action()
        finally:
            self._pruning = False

    def get_player(self, player_id: str) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise ValueError("unknown player")

    def legal_actions(self, player_id: str | None) -> list[dict]:
        if not player_id or player_id != self.to_act or not self.live_hand():
            return []
        player = self.get_player(player_id)
        to_call = max(0, self.current_bet - player.bet)
        actions = [{"action": "fold"}]
        if to_call == 0:
            actions.append({"action": "check"})
        else:
            actions.append({"action": "call", "amount": to_call})
        if player.stack > to_call:
            actions.append({"action": "raise", "min_amount": self.current_bet + 1, "max_amount": player.bet + player.stack})
        if player.stack > 0:
            actions.append({"action": "allin", "amount": player.bet + player.stack})
        return actions

    def live_hand(self) -> bool:
        return self.stage in {"preflop", "flop", "turn", "river"}

    def active_players(self) -> list[Player]:
        if self.live_hand():
            return [p for p in self.players if not p.folded and len(p.cards) == 2]
        return [p for p in self.players if not p.folded]

    def actionable_players(self) -> list[Player]:
        return [p for p in self.active_players() if p.connected and not p.all_in and (not self.live_hand() or len(p.cards) == 2)]

    def next_eligible_index(self, start: int) -> int:
        for offset in range(1, len(self.players) + 1):
            idx = (start + offset) % len(self.players)
            p = self.players[idx]
            if p.connected and p.stack > 0:
                return idx
        raise ValueError("no eligible player")

    def next_actionable_index(self, start: int) -> int | None:
        for offset in range(1, len(self.players) + 1):
            idx = (start + offset) % len(self.players)
            p = self.players[idx]
            if p in self.actionable_players():
                return idx
        return None

    def commit(self, player: Player, amount: int) -> None:
        paid = min(max(amount, 0), player.stack)
        player.stack -= paid
        player.bet += paid
        player.invested += paid
        self.pot += paid
        if player.stack == 0:
            player.all_in = True

    def fold_player(self, player: Player) -> None:
        player.folded = True
        self.pending.discard(player.id)

    def after_action(self) -> None:
        live = self.active_players()
        if self.live_hand() and len(live) == 0:
            self.stage = "ended"
            self.to_act = None
            self.pending = set()
            self.event("hand ended with no live players")
            return
        if self.live_hand() and len(live) == 1:
            self.award(live, "everyone else folded")
            return
        if not self.live_hand():
            return
        if self.pending:
            start = self.index_of(self.to_act) if self.to_act else self.dealer
            for _ in range(len(self.players)):
                idx = self.next_actionable_index(start)
                if idx is None:
                    break
                candidate = self.players[idx]
                self.to_act = candidate.id
                if candidate.id in self.pending:
                    return
                start = idx
        self.advance()

    def advance(self) -> None:
        for p in self.players:
            p.bet = 0
        self.current_bet = 0
        next_stage = {"preflop": "flop", "flop": "turn", "turn": "river", "river": "showdown"}[self.stage]
        deal = {"flop": 3, "turn": 1, "river": 1, "showdown": 0}[next_stage]
        self.stage = next_stage
        for _ in range(deal):
            self.community.append(self.deck.pop())
        if self.stage == "showdown" or len(self.actionable_players()) <= 1:
            self.showdown()
            return
        self.pending = {p.id for p in self.actionable_players()}
        idx = self.next_actionable_index(self.dealer)
        self.to_act = self.players[idx].id if idx is not None else None
        self.event(f"advanced to {self.stage}")

    def showdown(self) -> None:
        contenders = self.active_players()
        ranks = {p.id: hand_rank(p.cards + self.community) for p in contenders}
        self.award_side_pots(contenders, ranks)

    def award(self, winners: list[Player], reason: str, amount: int | None = None) -> None:
        pot_amount = self.pot if amount is None else amount
        share = pot_amount // len(winners)
        extra = pot_amount % len(winners)
        self.winners = []
        for i, p in enumerate(winners):
            amount = share + (1 if i < extra else 0)
            p.stack += amount
            self.winners.append({"id": p.id, "name": p.name, "amount": amount, "reason": reason})
        self.stage = "showdown"
        self.to_act = None
        self.pending = set()
        self.event(", ".join(f"{w['name']} wins {w['amount']} ({w['reason']})" for w in self.winners))

    def award_side_pots(self, contenders: list[Player], ranks: dict[str, tuple[int, str]]) -> None:
        self.winners = []
        levels = sorted({p.invested for p in self.players if p.invested > 0})
        previous = 0
        for level in levels:
            contributors = [p for p in self.players if p.invested >= level]
            pot_amount = (level - previous) * len(contributors)
            eligible = [p for p in contenders if p.invested >= level and not p.folded]
            if pot_amount <= 0 or not eligible:
                previous = level
                continue
            best_score = max(ranks[p.id][0] for p in eligible)
            winners = [p for p in eligible if ranks[p.id][0] == best_score]
            share = pot_amount // len(winners)
            extra = pot_amount % len(winners)
            reason = ranks[winners[0].id][1]
            for i, player in enumerate(winners):
                won = share + (1 if i < extra else 0)
                player.stack += won
                self.winners.append({"id": player.id, "name": player.name, "amount": won, "reason": reason})
            previous = level
        self.stage = "showdown"
        self.to_act = None
        self.pending = set()
        self.event(", ".join(f"{w['name']} wins {w['amount']} ({w['reason']})" for w in self.winners))

    def index_of(self, player_id: str | None) -> int:
        for i, p in enumerate(self.players):
            if p.id == player_id:
                return i
        return self.dealer
