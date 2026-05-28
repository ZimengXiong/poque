import React, { useState, useEffect } from 'react';
import type { Player, GameState } from '../services/api';

interface ActionControlsProps {
  player: Player;
  gameState: GameState;
  onSubmitAction: (action: 'fold' | 'check' | 'call' | 'bet' | 'raise' | 'allin', amount: number) => void;
}

export const ActionControls: React.FC<ActionControlsProps> = ({
  player,
  gameState,
  onSubmitAction
}) => {
  const { chips, bet: playerRoundBet } = player;
  const { currentBet, minRaise, pot, bigBlind } = gameState;

  // Calculate betting metrics
  const toCall = currentBet - playerRoundBet;

  // State for slider/bet size
  const [betVal, setBetVal] = useState<number>(minRaise);

  // Sync bet amount whenever turn changes or minRaise updates
  useEffect(() => {
    // If we can bet, start at 2x BB or minRaise
    const initialBet = Math.min(chips, Math.max(minRaise, currentBet > 0 ? minRaise : bigBlind));
    setBetVal(initialBet);
  }, [minRaise, currentBet, chips, bigBlind]);

  // Adjust sliders if input is typed directly
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let val = parseInt(e.target.value) || 0;
    if (val > chips) val = chips;
    setBetVal(val);
  };

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setBetVal(parseInt(e.target.value) || 0);
  };

  // Quick multipliers
  const setQuickBet = (multiplier: 'min' | '2bb' | '3bb' | 'half-pot' | 'pot' | 'all-in') => {
    let target = minRaise;

    switch (multiplier) {
      case 'min':
        target = minRaise;
        break;
      case '2bb':
        target = bigBlind * 2;
        break;
      case '3bb':
        target = bigBlind * 3;
        break;
      case 'half-pot':
        target = Math.max(minRaise, Math.floor(pot / 2));
        break;
      case 'pot':
        target = Math.max(minRaise, pot);
        break;
      case 'all-in':
        target = chips;
        break;
    }

    // Clamp value
    target = Math.min(chips, Math.max(target, currentBet > 0 ? minRaise : bigBlind));
    setBetVal(target);
  };

  // Determine button displays
  const canCheck = toCall === 0;
  const canCall = toCall > 0 && chips > 0;
  const canBet = currentBet === 0 && chips > 0;
  const canRaise = currentBet > 0 && chips > toCall && chips >= minRaise - playerRoundBet;

  const isAllInRaise = betVal === chips;
  const isAllInCall = toCall >= chips;

  return (
    <div className="actions-container" style={{ animation: 'scale-in 0.3s' }}>
      
      {/* Slider controls - only show if betting or raising is legal */}
      {(canBet || canRaise) && (
        <div className="bet-slider-area">
          <div className="slider-labels">
            <span>Min: ${minRaise}</span>
            <span style={{ fontWeight: 'bold', color: '#fff' }}>
              Selected: ${betVal} {betVal === chips && '🔥 (ALL-IN)'}
            </span>
            <span>Max: ${chips}</span>
          </div>

          <div className="slider-wrapper">
            <input
              type="range"
              className="pq-slider"
              min={minRaise}
              max={chips}
              step={bigBlind / 2}
              value={betVal}
              onChange={handleSliderChange}
            />
            <input
              type="number"
              className="bet-input"
              value={betVal}
              onChange={handleInputChange}
              min={minRaise}
              max={chips}
            />
          </div>

          {/* Quick bet multipliers */}
          <div className="quick-multipliers">
            <button className="quick-mult-btn" onClick={() => setQuickBet('min')}>Min</button>
            <button className="quick-mult-btn" onClick={() => setQuickBet('2bb')}>2x BB</button>
            <button className="quick-mult-btn" onClick={() => setQuickBet('3bb')}>3x BB</button>
            <button className="quick-mult-btn" onClick={() => setQuickBet('half-pot')}>1/2 Pot</button>
            <button className="quick-mult-btn" onClick={() => setQuickBet('pot')}>Pot</button>
            <button className="quick-mult-btn" onClick={() => setQuickBet('all-in')} style={{ borderColor: 'var(--accent-crimson)', color: '#fca5a5' }}>All-In</button>
          </div>
        </div>
      )}

      {/* Primary fold/check/call/raise actions grid */}
      <div className="action-buttons-grid">
        <button
          className="pq-btn-action fold"
          onClick={() => onSubmitAction('fold', 0)}
        >
          <span>Fold</span>
          <span className="subtext">Muck Hand</span>
        </button>

        {canCheck && (
          <button
            className="pq-btn-action check"
            onClick={() => onSubmitAction('check', 0)}
          >
            <span>Check</span>
            <span className="subtext">Pass Turn</span>
          </button>
        )}

        {canCall && (
          <button
            className="pq-btn-action call"
            onClick={() => onSubmitAction(isAllInCall ? 'allin' : 'call', toCall)}
          >
            <span>{isAllInCall ? 'All-In Call' : 'Call'}</span>
            <span className="subtext">${Math.min(chips, toCall)}</span>
          </button>
        )}

        {canBet && (
          <button
            className="pq-btn-action raise-bet"
            onClick={() => onSubmitAction(isAllInRaise ? 'allin' : 'bet', betVal)}
            disabled={betVal < bigBlind || betVal > chips}
          >
            <span>{isAllInRaise ? 'All-In Bet' : 'Bet'}</span>
            <span className="subtext">${betVal}</span>
          </button>
        )}

        {canRaise && (
          <button
            className="pq-btn-action raise-bet"
            onClick={() => onSubmitAction(isAllInRaise ? 'allin' : 'raise', betVal)}
            disabled={betVal < minRaise || betVal > chips}
          >
            <span>{isAllInRaise ? 'All-In Raise' : 'Raise'}</span>
            <span className="subtext">${betVal}</span>
          </button>
        )}
      </div>

    </div>
  );
};
