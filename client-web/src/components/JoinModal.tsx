import React, { useState, useEffect } from 'react';
import { getBrowserFingerprint } from '../utils/fingerprint';
import type { Player } from '../services/api';

interface JoinModalProps {
  players: Player[];
  onJoin: (displayName: string) => void;
  isDemoMode?: boolean;
  onToggleDemo?: (demo: boolean) => void;
}

export const JoinModal: React.FC<JoinModalProps> = ({ players, onJoin }) => {
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
      <div className="onboarding-card glass-panel">
        <h1 className="onboarding-logo">P-O-Q-U-E</h1>
        <p className="onboarding-subtitle">Texas Hold'em</p>

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
