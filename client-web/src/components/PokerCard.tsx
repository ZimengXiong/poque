import React from 'react';

interface PokerCardProps {
  cardCode?: string; // e.g. "As", "10d", "Jh"
  className?: string;
}

export const PokerCard: React.FC<PokerCardProps> = ({ cardCode, className = '' }) => {
  // If no card code is provided, render card back
  if (!cardCode) {
    return <div className={`poker-card back ${className}`} />;
  }

  // Parse card rank and suit
  const rank = cardCode.slice(0, -1);
  const suitLetter = cardCode.slice(-1).toLowerCase();

  let suitSymbol = '♠';
  let colorClass = '';

  switch (suitLetter) {
    case 's':
      suitSymbol = '♠';
      colorClass = 'spade'; // Black
      break;
    case 'h':
      suitSymbol = '♥';
      colorClass = 'red'; // Red (Hearts)
      break;
    case 'd':
      suitSymbol = '♦';
      colorClass = 'blue'; // Blue (Diamonds) - Premium four-color deck!
      break;
    case 'c':
      suitSymbol = '♣';
      colorClass = 'green'; // Green (Clubs) - Premium four-color deck!
      break;
  }

  // Display style adaptations for double digit 10
  const displayRank = rank === '10' ? '10' : rank;

  return (
    <div className={`poker-card ${colorClass} ${className}`}>
      <div className="top-left">
        <span>{displayRank}</span>
        <span style={{ fontSize: '0.65rem', marginTop: '2px' }}>{suitSymbol}</span>
      </div>
      <div className="suit-large">{suitSymbol}</div>
      <div className="top-left" style={{ transform: 'rotate(180deg)', alignSelf: 'flex-end' }}>
        <span>{displayRank}</span>
        <span style={{ fontSize: '0.65rem', marginTop: '2px' }}>{suitSymbol}</span>
      </div>
    </div>
  );
};
