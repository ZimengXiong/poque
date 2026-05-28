import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  Volume2, 
  VolumeX, 
  Play, 
  LogOut, 
  User, 
  RefreshCw, 
  Award
} from 'lucide-react';

import { getBrowserFingerprint } from './utils/fingerprint';
import { PoqueAPI } from './services/api';
import type { GameState } from './services/api';
import { JoinModal } from './components/JoinModal';
import { PlayerSeat } from './components/PlayerSeat';
import { PokerCard } from './components/PokerCard';
import { ActionControls } from './components/ActionControls';
import { EventLog } from './components/EventLog';

// Web Audio API Casino Sound Synthesizer
function playPokerSound(type: 'chip' | 'card' | 'win' | 'shuffle') {
  if (typeof window === 'undefined') return;
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    
    if (type === 'chip') {
      // Ceramic poker chip clack
      const now = ctx.currentTime;
      const playClick = (time: number) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = 'sine';
        osc.frequency.setValueAtTime(1700 + Math.random() * 200, time);
        gain.gain.setValueAtTime(0.12, time);
        gain.gain.exponentialRampToValueAtTime(0.001, time + 0.035);
        osc.start(time);
        osc.stop(time + 0.04);
      };
      playClick(now);
      playClick(now + 0.045);
    } else if (type === 'card') {
      // Soft card sliding brush sound
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const filter = ctx.createBiquadFilter();
      osc.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(280, now);
      osc.frequency.exponentialRampToValueAtTime(70, now + 0.12);
      filter.type = 'lowpass';
      filter.frequency.setValueAtTime(500, now);
      gain.gain.setValueAtTime(0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
      osc.start(now);
      osc.stop(now + 0.13);
    } else if (type === 'win') {
      // Winning arpeggio
      const now = ctx.currentTime;
      const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
      notes.forEach((freq, idx) => {
        const time = now + idx * 0.07;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, time);
        gain.gain.setValueAtTime(0.06, time);
        gain.gain.exponentialRampToValueAtTime(0.001, time + 0.3);
        osc.start(time);
        osc.stop(time + 0.35);
      });
    } else if (type === 'shuffle') {
      // Shuffling cards friction sweep
      const now = ctx.currentTime;
      for (let i = 0; i < 6; i++) {
        const time = now + i * 0.05;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(90 + Math.random() * 120, time);
        gain.gain.setValueAtTime(0.03, time);
        gain.gain.exponentialRampToValueAtTime(0.001, time + 0.04);
        osc.start(time);
        osc.stop(time + 0.05);
      }
    }
  } catch (e) {
    console.warn('AudioContext play error', e);
  }
}

function App() {
  const fingerprint = getBrowserFingerprint();
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [isDemoMode, setIsDemoMode] = useState(true);
  const [isJoined, setIsJoined] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [loading, setLoading] = useState(true);

  // References to keep track of state deltas to trigger sound effects
  const prevPotRef = useRef<number>(0);
  const prevPhaseRef = useRef<string>('WAITING');
  const prevCardsCountRef = useRef<number>(0);

  // Sync state and check connection
  useEffect(() => {
    // 1. Subscribe to API / Simulation updates
    const unsubscribe = PoqueAPI.subscribe((state, demoStatus) => {
      setGameState(state);
      setIsDemoMode(demoStatus);

      // Verify if the local fingerprint exists and is connected
      const selfIndex = state.players.findIndex(p => p.id === fingerprint && p.connected);
      if (selfIndex !== -1 && state.players[selfIndex].displayName) {
        setIsJoined(true);
      } else {
        setIsJoined(false);
      }

      // 2. Play game sound effects dynamically on state deltas
      if (soundEnabled) {
        // Pot increased -> chips clacking
        if (state.pot > prevPotRef.current && prevPotRef.current > 0) {
          playPokerSound('chip');
        }
        // Cards dealt to community -> deal card slide
        if (state.communityCards.length > prevCardsCountRef.current) {
          playPokerSound('card');
        }
        // Hand phase changed to PREFLOP -> Shuffle deck
        if (state.handPhase === 'PREFLOP' && prevPhaseRef.current !== 'PREFLOP') {
          playPokerSound('shuffle');
        }
        // Hand phase changed to SHOWDOWN -> Win chime
        if (state.handPhase === 'SHOWDOWN' && prevPhaseRef.current !== 'SHOWDOWN') {
          playPokerSound('win');
        }
      }

      // Sync refs
      prevPotRef.current = state.pot;
      prevPhaseRef.current = state.handPhase;
      prevCardsCountRef.current = state.communityCards.length;
    });

    // 2. Perform connection checks to see if local backend is available
    const checkConn = async () => {
      setLoading(true);
      await PoqueAPI.checkConnection();
      await PoqueAPI.getGameState();
      setLoading(false);
    };

    checkConn();

    // 3. Keepalive / polling status interval
    const interval = setInterval(() => {
      PoqueAPI.keepalive();
      PoqueAPI.getGameState();
    }, 1500);

    return () => {
      unsubscribe();
      clearInterval(interval);
    };
  }, [fingerprint, soundEnabled]);

  // Seating rotation helper
  // Computes the seat index clock-wise relative to the current player's bottom seat (0)
  const getRelativeSeatPosition = useCallback((playerIndex: number): number => {
    if (!gameState) return playerIndex % 6;
    
    // Find index of current user
    const selfIdx = gameState.players.findIndex(p => p.id === fingerprint);
    if (selfIdx === -1) return playerIndex % 6;

    const totalSeats = gameState.players.length;
    return (playerIndex - selfIdx + totalSeats) % totalSeats;
  }, [gameState, fingerprint]);

  // Handlers
  const handleJoin = async (displayName: string) => {
    const ok = await PoqueAPI.joinGame(displayName);
    if (ok) {
      setIsJoined(true);
      if (soundEnabled) playPokerSound('chip');
    }
  };

  const handleLeave = async () => {
    if (window.confirm('Are you sure you want to leave the table?')) {
      const ok = await PoqueAPI.leaveGame();
      if (ok) {
        setIsJoined(false);
      }
    }
  };

  const handleStartHand = async () => {
    if (soundEnabled) playPokerSound('shuffle');
    await PoqueAPI.startHand();
  };

  const handleSubmitAction = async (action: 'fold' | 'check' | 'call' | 'bet' | 'raise' | 'allin', amount: number) => {
    if (soundEnabled) {
      if (action === 'fold') playPokerSound('card');
      else playPokerSound('chip');
    }
    await PoqueAPI.submitAction(action, amount);
  };

  const handleForceToggleMode = (demo: boolean) => {
    setIsDemoMode(demo);
    PoqueAPI.setDemoMode(demo);
  };

  if (loading && !gameState) {
    return (
      <div className="onboarding-screen">
        <div style={{ textAlign: 'center' }}>
          <RefreshCw className="animate-spin" size={48} style={{ color: 'var(--primary-gold)', animation: 'spin 1.5s linear infinite', marginBottom: '16px' }} />
          <h2 style={{ fontFamily: 'var(--font-sans)', fontWeight: 600 }}>Initializing P-O-Q-U-E Poker Room...</h2>
        </div>
      </div>
    );
  }

  // Get active self player info
  const selfPlayer = gameState?.players.find(p => p.id === fingerprint);
  const isMyTurn = gameState?.currentTurnPlayerId === fingerprint && gameState?.handInProgress;

  // Active thinking player name
  const thinkingPlayer = gameState?.players.find(p => p.id === gameState.currentTurnPlayerId);

  return (
    <div className="app-container">
      {/* HEADER COMPONENT */}
      <header className="app-header">
        <div className="brand">
          <span className="brand-logo">POQUE</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* Active Mode Status Badge */}
          <div 
            onClick={() => handleForceToggleMode(!isDemoMode)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '0.75rem',
              fontWeight: 700,
              padding: '6px 12px',
              borderRadius: '8px',
              cursor: 'pointer',
              background: isDemoMode ? 'rgba(56, 189, 248, 0.08)' : 'rgba(229, 192, 96, 0.08)',
              border: isDemoMode ? '1px solid rgba(56, 189, 248, 0.25)' : '1px solid rgba(229, 192, 96, 0.25)',
              color: isDemoMode ? 'var(--accent-cyan)' : 'var(--primary-gold)',
              transition: 'all 0.2s ease',
              userSelect: 'none'
            }}
            title="Click to toggle gameplay mode"
          >
            <span style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              background: isDemoMode ? 'var(--accent-cyan)' : 'var(--primary-gold)',
              boxShadow: isDemoMode ? '0 0 8px var(--accent-cyan)' : '0 0 8px var(--primary-gold)',
              display: 'inline-block'
            }} />
            <span>{isDemoMode ? 'SOLO DEMO' : 'LIVE SERVER'}</span>
          </div>

          {isJoined && selfPlayer && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.04)', padding: '6px 12px', borderRadius: '8px', border: '1px solid var(--border-light)' }}>
              <User size={14} style={{ color: 'var(--primary-gold)' }} />
              <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>{selfPlayer.displayName}</span>
              <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)', borderLeft: '1px solid rgba(255,255,255,0.2)', paddingLeft: '8px' }}>
                ${selfPlayer.chips}
              </span>
            </div>
          )}

          {/* Sound switch */}
          <button 
            className="audio-toggle-btn"
            onClick={() => setSoundEnabled(!soundEnabled)}
            title={soundEnabled ? 'Mute Sounds' : 'Unmute Sounds'}
          >
            {soundEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
        </div>
      </header>

      {/* MAIN GAMING SHELL CONTAINER */}
      <div className="main-stage">
        
        {/* radial green felt poker table arena */}
        <section className="table-arena glass-panel">
          
          {/* oval felt */}
          <div className="felt-table">
            
            {/* Center Area: Community Cards and Pot */}
            <div className="community-cards-area">
              {gameState?.pot !== undefined && gameState.pot > 0 && (
                <div className="pot-display">
                  <span>💰 TOTAL POT:</span>
                  <span style={{ fontFamily: 'var(--font-mono)' }}>${gameState.pot}</span>
                </div>
              )}

              {/* Showdown victory banner */}
              {gameState?.handPhase === 'SHOWDOWN' && (
                <div className="showdown-banner" style={{ display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                  <Award size={18} />
                  <span>SHOWDOWN - WINNERS DECLARED</span>
                </div>
              )}

              {/* The 5 Community slots */}
              <div className="cards-row">
                {gameState?.communityCards.map((card, i) => (
                  <PokerCard key={`cc-${i}`} cardCode={card} />
                ))}
                {/* Visual empty card slots placeholder to guide layout */}
                {gameState?.handInProgress && Array.from({ length: 5 - (gameState?.communityCards?.length || 0) }).map((_, idx) => (
                  <div 
                    key={`slot-${idx}`} 
                    className="poker-card" 
                    style={{ 
                      background: 'rgba(0, 0, 0, 0.2)', 
                      border: '1px dashed rgba(255,255,255,0.15)',
                      boxShadow: 'none' 
                    }} 
                  />
                ))}
              </div>
            </div>

          </div>

          {/* Seating ring overlay positioning */}
          {gameState && (
            <div className="player-seats-container">
              {gameState.players.map((player, idx) => {
                const relativePos = getRelativeSeatPosition(idx);
                return (
                  <PlayerSeat
                    key={player.id}
                    player={player}
                    seatPosition={relativePos}
                    currentBet={gameState.currentBet}
                    isSelf={player.id === fingerprint}
                    revealCards={gameState.handPhase === 'SHOWDOWN'}
                  />
                );
              })}
            </div>
          )}

        </section>

        {/* SIDE PANEL: SCROLL EVENT FEED & POCKET INTERACTION MODULE */}
        <aside className="sidebar-panel">
          
          {/* Monospace console list */}
          <EventLog logs={gameState?.eventLog || []} />

          {/* User interaction action panel */}
          <div className="player-dash-panel glass-panel">
            {isJoined && selfPlayer ? (
              <>
                {/* Game state controls depending on turn / phase */}
                {!gameState?.handInProgress ? (
                  <div className="pre-game-controls" style={{ animation: 'scale-in 0.25s' }}>
                    <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.85rem', marginBottom: '8px' }}>
                      Ready to start the next deal?
                    </p>
                    <button className="pq-btn" onClick={handleStartHand}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'center' }}>
                        <Play size={16} fill="currentColor" />
                        <span>Start Next Hand</span>
                      </div>
                    </button>
                    <button className="pq-btn secondary" onClick={handleLeave} style={{ marginTop: '4px', fontSize: '0.8rem', padding: '8px 12px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                        <LogOut size={12} />
                        <span>Leave Table</span>
                      </div>
                    </button>
                  </div>
                ) : isMyTurn ? (
                  <ActionControls
                    player={selfPlayer}
                    gameState={gameState}
                    onSubmitAction={handleSubmitAction}
                  />
                ) : (
                  <div style={{ textAlign: 'center', animation: 'scale-in 0.3s' }}>
                    {thinkingPlayer ? (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                        <RefreshCw className="animate-spin" size={24} style={{ color: 'var(--primary-gold)', animation: 'spin 1.5s linear infinite' }} />
                        <p style={{ fontSize: '0.9rem', color: '#fff', fontWeight: 600 }}>
                          {thinkingPlayer.displayName} in the tank...
                        </p>
                        <p style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.4)' }}>
                          Wait for opponent to declare action.
                        </p>
                      </div>
                    ) : (
                      <p style={{ fontSize: '0.9rem', color: 'rgba(255,255,255,0.5)' }}>
                        Waiting for action...
                      </p>
                    )}
                  </div>
                )}
              </>
            ) : (
              <div style={{ textAlign: 'center' }}>
                <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '0.85rem' }}>
                  Please log in to join the poker session.
                </p>
              </div>
            )}
          </div>

        </aside>

      </div>

      {/* LOGIN ONBOARDING OVERLAY GATEWAY */}
      {!isJoined && gameState && (
        <JoinModal
          players={gameState.players}
          onJoin={handleJoin}
          isDemoMode={isDemoMode}
          onToggleDemo={handleForceToggleMode}
        />
      )}
    </div>
  );
}

export default App;
