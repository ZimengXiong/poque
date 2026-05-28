export interface Player {
  id: string;
  displayName: string;
  chips: number;
  bet: number;
  isFolded: boolean;
  isActive: boolean;
  isDealer: boolean;
  isSmallBlind: boolean;
  isBigBlind: boolean;
  cards?: string[];
  lastAction?: string;
  connected: boolean;
}

export interface GameEvent {
  id: string;
  timestamp: number;
  message: string;
  type: 'system' | 'action' | 'win' | 'chat';
}

export interface GameState {
  roomName: string;
  gameStarted: boolean;
  handInProgress: boolean;
  players: Player[];
  communityCards: string[];
  pot: number;
  currentTurnPlayerId: string | null;
  dealerIndex: number;
  smallBlind: number;
  bigBlind: number;
  currentBet: number;
  minRaise: number;
  eventLog: GameEvent[];
  handPhase: 'WAITING' | 'PREFLOP' | 'FLOP' | 'TURN' | 'RIVER' | 'SHOWDOWN';
  winners?: unknown[];
  lastError?: string | null;
  legalActions?: Array<{ action: string; amount?: number; min?: number; max?: number } | string>;
}

const API_BASE = '/api';
const SESSION_BASE = '/session';
const browserFingerprint = () => getBrowserFingerprint();
const jsonHeaders = () => ({
  'Content-Type': 'application/json',
  'X-Browser-Fingerprint': browserFingerprint(),
});

function mapStage(stage: string): GameState['handPhase'] {
  if (stage === 'preflop') return 'PREFLOP';
  if (stage === 'flop') return 'FLOP';
  if (stage === 'turn') return 'TURN';
  if (stage === 'river') return 'RIVER';
  if (stage === 'showdown') return 'SHOWDOWN';
  return 'WAITING';
}

function normalizeActionName(action: unknown): string {
  if (typeof action === 'string') return action;
  if (action && typeof action === 'object' && 'action' in action) return String((action as { action: unknown }).action);
  return '';
}

function mapState(raw: any, viewerPlayerId: string | null = null): GameState {
  const browserId = getBrowserFingerprint();
  const stage = mapStage(raw.stage);
  const players: Player[] = (raw.players || []).map((player: any) => {
    const seat = Number(player.seat || 0);
    return {
      id: player.id === viewerPlayerId ? browserId : player.id,
      displayName: player.name || 'Player',
      chips: Number(player.stack || 0),
      bet: Number(player.bet || 0),
      isFolded: Boolean(player.folded),
      isActive: raw.to_act === player.id,
      isDealer: raw.dealer_seat === seat,
      isSmallBlind: false,
      isBigBlind: false,
      cards: player.cards || [],
      lastAction: player.all_in ? 'All-in' : player.folded ? 'Folded' : undefined,
      connected: Boolean(player.connected),
    };
  });

  const actions = raw.legal_actions || [];
  const minRaiseAction = actions.find((action: any) => normalizeActionName(action) === 'raise' || normalizeActionName(action) === 'bet');
  const minRaise = typeof minRaiseAction === 'object' && minRaiseAction
    ? Number(minRaiseAction.min || minRaiseAction.amount || raw.big_blind || 20)
    : Number(raw.current_bet || raw.big_blind || 20);

  return {
    roomName: raw.room || 'main',
    gameStarted: raw.stage !== 'lobby',
    handInProgress: raw.stage !== 'lobby' && raw.stage !== 'showdown',
    players,
    communityCards: raw.community || [],
    pot: Number(raw.pot || 0),
    currentTurnPlayerId: raw.to_act === viewerPlayerId ? browserId : raw.to_act || null,
    dealerIndex: Number(raw.dealer_seat || 0),
    smallBlind: Number(raw.small_blind || 10),
    bigBlind: Number(raw.big_blind || 20),
    currentBet: Number(raw.current_bet || 0),
    minRaise,
    eventLog: (raw.events || []).map((event: any, index: number) => ({
      id: `${event.at || index}-${index}`,
      timestamp: Number(event.at || Date.now() / 1000) * 1000,
      message: event.message || String(event),
      type: String(event.message || '').toLowerCase().includes('win') ? 'win' : 'action',
    })),
    handPhase: stage,
    winners: raw.winners || [],
    lastError: raw.last_error || null,
    legalActions: actions,
  };
}

export class PoqueAPI {
  private static playerId: string | null = localStorage.getItem('poque_player_id');
  private static callbacks: ((state: GameState, isDemo: boolean) => void)[] = [];
  private static localState: GameState | null = null;

  public static subscribe(callback: (state: GameState, isDemo: boolean) => void) {
    this.callbacks.push(callback);
    if (this.localState) callback(this.localState, false);
    return () => {
      this.callbacks = this.callbacks.filter((item) => item !== callback);
    };
  }

  private static notify() {
    if (!this.localState) return;
    this.callbacks.forEach((callback) => callback(this.localState as GameState, false));
  }

  public static async checkConnection(): Promise<boolean> {
    const res = await fetch(`${SESSION_BASE}/status`, { headers: jsonHeaders() });
    if (!res.ok) return false;
    const data = await res.json();
    if (data.player_id) {
      this.playerId = data.player_id;
      localStorage.setItem('poque_player_id', data.player_id);
    }
    return true;
  }

  public static setDemoMode(_active: boolean) {
    this.notify();
  }

  public static async getGameState(): Promise<GameState> {
    const qs = this.playerId ? `?player_id=${encodeURIComponent(this.playerId)}` : '';
    const res = await fetch(`${API_BASE}/state${qs}`, { headers: jsonHeaders() });
    if (!res.ok) throw new Error(`State request failed: ${res.status}`);
    const data = await res.json();
    this.localState = mapState(data.state, this.playerId);
    this.notify();
    return this.localState;
  }

  public static async joinGame(displayName: string): Promise<boolean> {
    const res = await fetch(`${SESSION_BASE}/join`, {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ name: displayName.trim().slice(0, 32) }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    this.playerId = data.player_id;
    localStorage.setItem('poque_player_id', data.player_id);
    this.localState = mapState(data.state, this.playerId);
    this.notify();
    return true;
  }

  public static async leaveGame(): Promise<boolean> {
    const res = await fetch(`${SESSION_BASE}/leave`, { method: 'POST', headers: jsonHeaders() });
    localStorage.removeItem('poque_player_id');
    this.playerId = null;
    if (res.ok) await this.getGameState();
    return res.ok;
  }

  public static async keepalive(): Promise<boolean> {
    if (!this.playerId) return false;
    const res = await fetch(`${SESSION_BASE}/keepalive`, { method: 'POST', headers: jsonHeaders() });
    return res.ok;
  }

  public static async startHand(): Promise<boolean> {
    const res = await fetch(`${API_BASE}/admin/start`, {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ small_blind: 10, big_blind: 20, starting_stack: 1000 }),
    });
    await this.getGameState();
    return res.ok;
  }

  public static async submitAction(action: 'fold' | 'check' | 'call' | 'bet' | 'raise' | 'allin', amount: number): Promise<boolean> {
    if (!this.playerId) return false;
    const res = await fetch(`${API_BASE}/action`, {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ player_id: this.playerId, action, amount }),
    });
    await this.getGameState();
    return res.ok;
  }
}
import { getBrowserFingerprint } from '../utils/fingerprint';
