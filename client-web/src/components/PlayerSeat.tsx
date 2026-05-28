import React from 'react';
import type { Player } from '../services/api';
import { PokerCard } from './PokerCard';

interface PlayerSeatProps {
  player: Player;
  seatPosition: number; // 0 (bottom) to 5 (clockwise)
  currentBet: number;
  isSelf: boolean;
  revealCards: boolean; // True during Showdown
}

export const PlayerSeat: React.FC<PlayerSeatProps> = ({
  player,
  seatPosition,
  // currentBet is kept in props for component signature but not destructured here to avoid unused variable warnings
  isSelf,
  revealCards
}) => {
  const {
    displayName,
    chips,
    bet,
    isFolded,
    isActive,
    isDealer,
    isSmallBlind,
    isBigBlind,
    cards = [],
    connected,
    lastAction
  } = player;

  // Determine what cards to render
  const shouldShowCards = cards.length > 0 && !isFolded && (isSelf || revealCards);
  const showCardBacks = cards.length > 0 && !isFolded && !isSelf && !revealCards;

  // Render player actions cleanly
  const renderActionTag = () => {
    if (!lastAction) return null;

    let typeClass = 'action-check';
    if (lastAction.toLowerCase().includes('fold')) typeClass = 'action-fold';
    else if (lastAction.toLowerCase().includes('call')) typeClass = 'action-call';
    else if (lastAction.toLowerCase().includes('raise') || lastAction.toLowerCase().includes('bet')) typeClass = 'action-raise';
    else if (lastAction.toLowerCase().includes('all-in')) typeClass = 'action-allin';
    else if (lastAction.toLowerCase().includes('blind')) typeClass = 'action-blind';

    return <div className={`player-action-tag ${typeClass}`}>{lastAction}</div>;
  };

  return (
    <div className={`player-seat pos-${seatPosition} ${isActive ? 'active' : ''} ${isFolded ? 'folded' : ''} ${!connected ? 'disconnected' : ''}`}>
      {/* Visual active border and stats */}
      <div className="player-card-bubble">
        {renderActionTag()}
        
        <div className="player-name">{displayName}</div>
        <div className="player-chips">${chips}</div>

        {/* Mini indicator cards underneath name for visual depth */}
        <div className="mini-cards-holder">
          {cards.length > 0 && !isFolded ? (
            <>
              <div className={`mini-card ${shouldShowCards ? '' : 'active'}`} />
              <div className={`mini-card ${shouldShowCards ? '' : 'active'}`} />
            </>
          ) : isFolded ? (
            <>
              <div className="mini-card mucked" />
              <div className="mini-card mucked" />
            </>
          ) : null}
        </div>

        {/* Dealer / Blind Poker tokens */}
        {isDealer && <div className="poker-token dealer">D</div>}
        {isSmallBlind && <div className="poker-token sb">SB</div>}
        {isBigBlind && <div className="poker-token bb">BB</div>}
      </div>

      {/* Opponent Card Backs or Actual Cards dealing above / next to the seat */}
      {cards.length > 0 && !isFolded && (
        <div 
          style={{
            display: 'flex',
            gap: '4px',
            marginTop: '8px',
            animation: 'scale-in 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275)'
          }}
        >
          {shouldShowCards ? (
            <>
              <PokerCard cardCode={cards[0]} />
              <PokerCard cardCode={cards[1]} />
            </>
          ) : showCardBacks ? (
            <>
              <PokerCard />
              <PokerCard />
            </>
          ) : null}
        </div>
      )}

      {/* Active bet placed on the felt in front of player */}
      {bet > 0 && (
        <div className="player-bet-bubble">
          <span style={{ color: '#ffea79', marginRight: '2px' }}>🪙</span>
          <span>${bet}</span>
        </div>
      )}
    </div>
  );
};
