import { getBrowserFingerprint } from '../utils/fingerprint';

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

const browserFingerprint = () => getBrowserFingerprint();

const now = Date.now();

function mockEvent(id: string, offsetMs: number, message: string, type: GameEvent['type'] = 'action'): GameEvent {
  return { id, timestamp: now - offsetMs, message, type };
}

function createMockState(): GameState {
  const selfId = browserFingerprint();
  return {
    roomName: 'Design Mock Table',
    gameStarted: true,
    handInProgress: true,
    players: [
      {
        id: selfId,
        displayName: 'You',
        chips: 1240,
        bet: 40,
        isFolded: false,
        isActive: false,
        isDealer: false,
        isSmallBlind: false,
        isBigBlind: false,
        cards: ['As', 'Qh'],
        lastAction: 'Call $40',
        connected: true,
      },
      {
        id: 'mock-maya',
        displayName: 'Maya',
        chips: 1680,
        bet: 120,
        isFolded: false,
        isActive: true,
        isDealer: true,
        isSmallBlind: false,
        isBigBlind: false,
        cards: ['8d', '8c'],
        lastAction: 'Raise $120',
        connected: true,
      },
      {
        id: 'mock-jules',
        displayName: 'Jules',
        chips: 920,
        bet: 0,
        isFolded: true,
        isActive: false,
        isDealer: false,
        isSmallBlind: true,
        isBigBlind: false,
        cards: ['2h', '7s'],
        lastAction: 'Folded',
        connected: true,
      },
      {
        id: 'mock-rin',
        displayName: 'Rin',
        chips: 2310,
        bet: 120,
        isFolded: false,
        isActive: false,
        isDealer: false,
        isSmallBlind: false,
        isBigBlind: true,
        cards: ['Kc', 'Jh'],
        lastAction: 'Call $120',
        connected: true,
      },
      {
        id: 'mock-sol',
        displayName: 'Sol',
        chips: 540,
        bet: 0,
        isFolded: false,
        isActive: false,
        isDealer: false,
        isSmallBlind: false,
        isBigBlind: false,
        cards: ['Td', '9d'],
        lastAction: 'Check',
        connected: false,
      },
      {
        id: 'mock-ivy',
        displayName: 'Ivy',
        chips: 1885,
        bet: 120,
        isFolded: false,
        isActive: false,
        isDealer: false,
        isSmallBlind: false,
        isBigBlind: false,
        cards: ['Ah', '5h'],
        lastAction: 'Call $120',
        connected: true,
      },
    ],
    communityCards: ['Qs', 'Jd', '4h'],
    pot: 520,
    currentTurnPlayerId: 'mock-maya',
    dealerIndex: 1,
    smallBlind: 10,
    bigBlind: 20,
    currentBet: 120,
    minRaise: 240,
    eventLog: [
      mockEvent('mock-1', 350000, 'You joined the mock design table.', 'system'),
      mockEvent('mock-2', 300000, 'Jules posted small blind $10.', 'action'),
      mockEvent('mock-3', 270000, 'Rin posted big blind $20.', 'action'),
      mockEvent('mock-4', 190000, 'Maya raised to $120.', 'action'),
      mockEvent('mock-5', 150000, 'Ivy called $120.', 'action'),
      mockEvent('mock-6', 90000, 'You called $40.', 'action'),
      mockEvent('mock-7', 30000, 'Flop dealt: Qs Jd 4h.', 'system'),
    ],
    handPhase: 'FLOP',
    winners: [],
    lastError: null,
    legalActions: [
      { action: 'fold' },
      { action: 'call', amount: 80 },
      { action: 'raise', min: 240, max: 1240 },
    ],
  };
}

export class PoqueAPI {
  private static callbacks: ((state: GameState, isDemo: boolean) => void)[] = [];
  private static localState: GameState | null = createMockState();
  private static isDemoMode: boolean = true;
  private static isServerAvailable: boolean = false;
  private static hasCheckedConnection: boolean = false;
  private static cachedPlayerId: string | null = null;

  public static getHasCheckedConnection() {
    return this.hasCheckedConnection;
  }

  public static getCachedPlayerId() {
    return this.cachedPlayerId;
  }

  public static subscribe(callback: (state: GameState, isDemo: boolean) => void) {
    this.callbacks.push(callback);
    // Initial emit
    if (this.localState) {
      callback(this.localState, this.isDemoMode);
    }
    return () => {
      this.callbacks = this.callbacks.filter((item) => item !== callback);
    };
  }

  private static notify() {
    if (!this.localState) return;
    this.callbacks.forEach((callback) => callback(this.localState as GameState, this.isDemoMode));
  }

  public static async checkConnection(): Promise<boolean> {
    try {
      const fingerprint = browserFingerprint();
      const res = await fetch('/session/status', {
        headers: {
          'x-browser-fingerprint': fingerprint,
        },
      });
      if (res.ok) {
        const data = await res.json();
        this.isServerAvailable = true;
        this.isDemoMode = false; // Disable demo mode by default if server works!
        if (data.player_id) {
          this.cachedPlayerId = data.player_id;
          localStorage.setItem('poque_player_id', data.player_id);
        }
        this.hasCheckedConnection = true;
        await this.syncStateFromServer();
        return true;
      }
    } catch (e) {
      console.warn('Backend server not reachable, running in Demo Mode', e);
    }
    this.isServerAvailable = false;
    this.isDemoMode = true;
    this.hasCheckedConnection = true;
    this.notify();
    return false;
  }

  public static setDemoMode(active: boolean) {
    this.isDemoMode = active;
    if (active) {
      this.localState = createMockState();
    } else {
      this.syncStateFromServer();
    }
    this.notify();
  }

  public static getDemoMode(): boolean {
    return this.isDemoMode;
  }

  public static getServerAvailable(): boolean {
    return this.isServerAvailable;
  }

  public static async getGameState(): Promise<GameState> {
    if (!this.isDemoMode && this.isServerAvailable) {
      await this.syncStateFromServer();
    }
    return this.localState as GameState;
  }

  private static async syncStateFromServer() {
    try {
      const fingerprint = browserFingerprint();
      const playerId = localStorage.getItem('poque_player_id') || '';
      
      const url = playerId ? `/api/state?player_id=${encodeURIComponent(playerId)}` : '/api/state';
      const res = await fetch(url, {
        headers: {
          'x-browser-fingerprint': fingerprint,
        },
      });
      if (res.ok) {
        const data = await res.json();
        if (data.ok && data.state) {
          this.mapUpstreamStateToLocal(data.state);
        }
      }
    } catch (e) {
      console.error('Failed to sync state from server', e);
    }
  }

  private static mapUpstreamStateToLocal(upstream: any) {
    // Sort players by seat so they are positioned correctly
    const rawPlayers = upstream.players || [];
    const sortedPlayers = [...rawPlayers].sort((a: any, b: any) => a.seat - b.seat);
    
    // Identify dealer seat and blinds seats
    const dealerSeat = upstream.dealer_seat;
    
    // Compute small blind and big blind seats
    const activeSeatPlayers = sortedPlayers.filter((p: any) => p.connected && p.stack > 0);
    let sbSeat = -1;
    let bbSeat = -1;
    
    if (activeSeatPlayers.length >= 2) {
      const dIdx = activeSeatPlayers.findIndex((p: any) => p.seat === dealerSeat);
      if (activeSeatPlayers.length === 2) {
        sbSeat = activeSeatPlayers[dIdx >= 0 ? dIdx : 0].seat;
        bbSeat = activeSeatPlayers[(dIdx + 1) % 2].seat;
      } else if (dIdx !== -1) {
        sbSeat = activeSeatPlayers[(dIdx + 1) % activeSeatPlayers.length].seat;
        bbSeat = activeSeatPlayers[(dIdx + 2) % activeSeatPlayers.length].seat;
      }
    }

    const mappedPlayers: Player[] = sortedPlayers.map((p: any) => {
      const isDealer = p.seat === dealerSeat;
      const isSmallBlind = p.seat === sbSeat;
      const isBigBlind = p.seat === bbSeat;
      
      // Map lastAction from events if we can find one or fallback
      let lastAction = undefined;
      if (p.folded) {
        lastAction = 'Folded';
      } else if (p.all_in) {
        lastAction = 'All-in';
      } else if (upstream.to_act === p.id) {
        lastAction = 'Thinking...';
      } else {
        // Try to look up the last event for this player to populate action
        const relevantEvents = (upstream.events || []).filter((e: any) => e.message.startsWith(p.name));
        if (relevantEvents.length > 0) {
          const msg = relevantEvents[relevantEvents.length - 1].message;
          lastAction = msg.substring(p.name.length).trim();
        }
      }

      return {
        id: p.id,
        displayName: p.name,
        chips: p.stack,
        bet: p.bet || 0,
        isFolded: p.folded || false,
        isActive: upstream.to_act === p.id,
        isDealer,
        isSmallBlind,
        isBigBlind,
        cards: p.cards,
        lastAction,
        connected: p.connected,
      };
    });

    // Map events
    const mappedEvents: GameEvent[] = (upstream.events || []).map((e: any, index: number) => {
      let type: GameEvent['type'] = 'action';
      const msg = e.message.toLowerCase();
      if (msg.includes('joined') || msg.includes('left') || msg.includes('timeout') || msg.includes('advanced') || msg.includes('started')) {
        type = 'system';
      } else if (msg.includes('win') || msg.includes('showdown')) {
        type = 'win';
      }
      return {
        id: `ev-${index}-${e.at}`,
        timestamp: e.at * 1000,
        message: e.message,
        type,
      };
    });

    // Map stage
    let handPhase: GameState['handPhase'] = 'WAITING';
    const stage = (upstream.stage || '').toLowerCase();
    if (stage === 'preflop') handPhase = 'PREFLOP';
    else if (stage === 'flop') handPhase = 'FLOP';
    else if (stage === 'turn') handPhase = 'TURN';
    else if (stage === 'river') handPhase = 'RIVER';
    else if (stage === 'showdown') handPhase = 'SHOWDOWN';

    // Map legal actions for frontend component ActionControls
    const mappedLegalActions = (upstream.legal_actions || []).map((la: any) => {
      if (la.action === 'raise') {
        return {
          action: 'raise',
          min: la.min_amount,
          max: la.max_amount,
        };
      }
      if (la.action === 'call') {
        return {
          action: 'call',
          amount: la.amount,
        };
      }
      return la;
    });

    // Minimum raise amount calculation
    let minRaise = upstream.big_blind || 20;
    const raiseAction = mappedLegalActions.find((a: any) => a.action === 'raise');
    if (raiseAction && raiseAction.min !== undefined) {
      minRaise = raiseAction.min;
    }

    this.localState = {
      roomName: upstream.room || 'Live Table',
      gameStarted: upstream.stage !== 'lobby',
      handInProgress: ['preflop', 'flop', 'turn', 'river', 'showdown'].includes(stage),
      players: mappedPlayers,
      communityCards: upstream.community || [],
      pot: upstream.pot || 0,
      currentTurnPlayerId: upstream.to_act,
      dealerIndex: upstream.dealer_seat - 1, // 0-indexed approximation
      smallBlind: upstream.small_blind || 10,
      bigBlind: upstream.big_blind || 20,
      currentBet: upstream.current_bet || 0,
      minRaise,
      eventLog: mappedEvents,
      handPhase,
      winners: upstream.winners,
      lastError: upstream.last_error,
      legalActions: mappedLegalActions,
    };
    
    this.notify();
  }

  public static async joinGame(displayName: string): Promise<boolean> {
    if (this.isDemoMode) {
      const selfId = browserFingerprint();
      this.localState = {
        ...(this.localState as GameState),
        players: (this.localState as GameState).players.map((player) => (
          player.id === selfId
            ? { ...player, displayName: displayName.trim().slice(0, 16) || 'You', connected: true }
            : player
        )),
      };
      this.notify();
      return true;
    }

    try {
      const fingerprint = browserFingerprint();
      const res = await fetch('/session/join', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-browser-fingerprint': fingerprint,
        },
        body: JSON.stringify({ name: displayName }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.ok && data.player_id) {
          this.cachedPlayerId = data.player_id;
          localStorage.setItem('poque_player_id', data.player_id);
          await this.syncStateFromServer();
          return true;
        }
      }
    } catch (e) {
      console.error('Failed to join game on server', e);
    }
    return false;
  }

  public static async leaveGame(): Promise<boolean> {
    if (this.isDemoMode) {
      return true;
    }

    try {
      const fingerprint = browserFingerprint();
      const res = await fetch('/session/leave', {
        method: 'POST',
        headers: {
          'x-browser-fingerprint': fingerprint,
        },
      });
      if (res.ok) {
        this.cachedPlayerId = null;
        localStorage.removeItem('poque_player_id');
        this.isDemoMode = true; // Drop back to demo mode on leave
        this.localState = createMockState();
        this.notify();
        return true;
      }
    } catch (e) {
      console.error('Failed to leave game on server', e);
    }
    return false;
  }

  public static async keepalive(): Promise<boolean> {
    if (this.isDemoMode) {
      return true;
    }

    try {
      const fingerprint = browserFingerprint();
      const res = await fetch('/session/keepalive', {
        method: 'POST',
        headers: {
          'x-browser-fingerprint': fingerprint,
        },
      });
      return res.ok;
    } catch (e) {
      console.error('Keepalive failed', e);
      return false;
    }
  }

  public static async startHand(): Promise<boolean> {
    if (this.isDemoMode) {
      this.localState = createMockState();
      this.notify();
      return true;
    }

    try {
      const fingerprint = browserFingerprint();
      const res = await fetch('/api/admin/start', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-browser-fingerprint': fingerprint,
        },
        body: JSON.stringify({
          small_blind: this.localState?.smallBlind || 10,
          big_blind: this.localState?.bigBlind || 20,
          starting_stack: 1000,
        }),
      });
      if (res.ok) {
        await this.syncStateFromServer();
        return true;
      }
    } catch (e) {
      console.error('Failed to start next hand', e);
    }
    return false;
  }

  public static async submitAction(
    action: 'fold' | 'check' | 'call' | 'bet' | 'raise' | 'allin',
    amount: number
  ): Promise<boolean> {
    if (this.isDemoMode) {
      const state = this.localState as GameState;
      const selfId = browserFingerprint();
      const label = action === 'allin' ? 'All-in' : `${action[0].toUpperCase()}${action.slice(1)}${amount ? ` $${amount}` : ''}`;
      
      this.localState = {
        ...state,
        pot: action === 'fold' || action === 'check' ? state.pot : state.pot + amount,
        currentTurnPlayerId: 'mock-rin',
        players: state.players.map((player) => (
          player.id === selfId
            ? {
                ...player,
                bet: action === 'fold' || action === 'check' ? player.bet : player.bet + amount,
                chips: action === 'fold' || action === 'check' ? player.chips : Math.max(0, player.chips - amount),
                isFolded: action === 'fold',
                isActive: false,
                lastAction: label,
              }
            : { ...player, isActive: player.id === 'mock-rin' }
        )),
        eventLog: [
          ...state.eventLog,
          mockEvent(`mock-user-${Date.now()}`, 0, `You selected ${label}.`, action === 'fold' ? 'system' : 'action'),
        ],
      };
      this.notify();
      return true;
    }

    try {
      const fingerprint = browserFingerprint();
      const playerId = localStorage.getItem('poque_player_id') || '';
      
      const res = await fetch('/api/action', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-browser-fingerprint': fingerprint,
        },
        body: JSON.stringify({
          player_id: playerId,
          action,
          amount,
        }),
      });
      if (res.ok) {
        await this.syncStateFromServer();
        return true;
      }
    } catch (e) {
      console.error('Failed to submit action to server', e);
    }
    return false;
  }
}
