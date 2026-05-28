import React, { useState, useEffect } from 'react';
import { getBrowserFingerprint } from '../utils/fingerprint';
import type { Player } from '../services/api';

interface JoinModalProps {
  players: Player[];
  onJoin: (displayName: string) => void;
  isDemoMode?: boolean;
  onToggleDemo?: (demo: boolean) => void;
}

export const JoinModal: React.FC<JoinModalProps> = ({ 
  players, 
  onJoin,
  isDemoMode = true,
  onToggleDemo
}) => {
  const [name, setName] = useState('');
  const [existingSessionPlayer, setExistingSessionPlayer] = useState<Player | null>(null);
  const fingerprint = getBrowserFingerprint();

  // Inspect the players list to see if the browser fingerprint matches an active player
  useEffect(() => {
    const matched = players.find(p => p.id === fingerprint && p.connected);
    if (matched && matched.displayName) {
      setExistingSessionPlayer(matched);
    } else {
      setExistingSessionPlayer(null);
    }
  }, [players, fingerprint]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (name.trim()) {
      onJoin(name.trim());
    }
  };

  const handleResume = () => {
    if (existingSessionPlayer) {
      onJoin(existingSessionPlayer.displayName);
    }
  };

  return (
    <div className="onboarding-screen">
      <div className="onboarding-card glass-panel" style={{ position: 'relative', overflow: 'hidden' }}>
        
        {/* Animated header background glow */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: '4px',
          background: isDemoMode 
            ? 'linear-gradient(to right, #3b82f6, #00f2fe)' 
            : 'linear-gradient(to right, #e5c060, #f1d279)',
          boxShadow: isDemoMode 
            ? '0 2px 20px rgba(0, 242, 254, 0.6)' 
            : '0 2px 20px rgba(229, 192, 96, 0.6)',
          transition: 'all 0.4s ease'
        }} />

        <h1 className="onboarding-logo">P-O-Q-U-E</h1>
        <p className="onboarding-subtitle">Texas Hold'em</p>

        {/* Dynamic Mode Switch Dashboard */}
        {onToggleDemo && (
          <div style={{
            background: 'rgba(255, 255, 255, 0.03)',
            border: '1px solid rgba(255, 255, 255, 0.06)',
            borderRadius: '12px',
            padding: '12px',
            marginBottom: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            animation: 'scale-in 0.3s'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'rgba(255, 255, 255, 0.6)' }}>
                GAMEPLAY MODE
              </span>
              <span style={{
                fontSize: '0.65rem',
                fontWeight: 800,
                padding: '2px 6px',
                borderRadius: '30px',
                background: isDemoMode ? 'rgba(56, 189, 248, 0.15)' : 'rgba(229, 192, 96, 0.15)',
                color: isDemoMode ? 'var(--accent-cyan)' : 'var(--primary-gold)',
                border: isDemoMode ? '1px solid rgba(56, 189, 248, 0.3)' : '1px solid rgba(229, 192, 96, 0.3)',
                letterSpacing: '0.05em'
              }}>
                {isDemoMode ? 'OFFLINE SIMULATOR' : 'MULTIPLAYER LIVE'}
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginTop: '4px' }}>
              <button
                type="button"
                onClick={() => onToggleDemo(true)}
                style={{
                  padding: '8px',
                  borderRadius: '6px',
                  border: isDemoMode ? '1px solid rgba(56, 189, 248, 0.5)' : '1px solid transparent',
                  background: isDemoMode ? 'rgba(56, 189, 248, 0.12)' : 'rgba(0, 0, 0, 0.2)',
                  color: isDemoMode ? '#fff' : 'rgba(255,255,255,0.4)',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
              >
                🤖 Solo Demo
              </button>
              <button
                type="button"
                onClick={() => onToggleDemo(false)}
                style={{
                  padding: '8px',
                  borderRadius: '6px',
                  border: !isDemoMode ? '1px solid rgba(229, 192, 96, 0.5)' : '1px solid transparent',
                  background: !isDemoMode ? 'rgba(229, 192, 96, 0.12)' : 'rgba(0, 0, 0, 0.2)',
                  color: !isDemoMode ? '#fff' : 'rgba(255,255,255,0.4)',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
              >
                🌐 Real Table
              </button>
            </div>
          </div>
        )}

        {existingSessionPlayer ? (
          <div style={{ animation: 'scale-in 0.3s' }}>
            <p style={{ marginBottom: '24px', fontSize: '1.05rem', color: '#e5c060' }}>
              Welcome back, <strong>{existingSessionPlayer.displayName}</strong>!
            </p>
            <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.85rem', marginBottom: '24px', lineHeight: '1.5' }}>
              An active session has been detected for your browser fingerprint:
              <br />
              <code style={{ fontSize: '0.75rem', marginTop: '6px', color: '#38bdf8' }}>{fingerprint}</code>
            </p>
            <button className="pq-btn" onClick={handleResume} style={{ marginBottom: '12px' }}>
              Resume Session
            </button>
            <button 
              className="pq-btn secondary" 
              onClick={() => {
                // Clear state to let them enter a new name
                setExistingSessionPlayer(null);
              }}
            >
              Join with new name
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ animation: 'scale-in 0.3s' }}>
            <p style={{ color: 'rgba(255,255,255,0.7)', fontSize: '0.9rem', marginBottom: '20px' }}>
              Enter a display name to grab a seat at the table.
            </p>

            <input
              type="text"
              className="text-input"
              placeholder="e.g. AceHigh"
              value={name}
              onChange={(e) => setName(e.target.value.slice(0, 16))}
              maxLength={16}
              required
              autoFocus
            />

            <button type="submit" className="pq-btn" disabled={!name.trim()}>
              Join Game
            </button>
          </form>
        )}

        <div style={{ marginTop: '30px', paddingTop: '20px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <p style={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.35)', marginTop: '8px', lineHeight: '1.3' }}>
            Your browser fingerprint is used only to reconnect this browser to its POQUE player session.
          </p>
        </div>
      </div>
    </div>
  );
};
