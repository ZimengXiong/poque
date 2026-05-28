import React, { useEffect, useRef } from 'react';
import type { GameEvent } from '../services/api';

interface EventLogProps {
  logs: GameEvent[];
}

export const EventLog: React.FC<EventLogProps> = ({ logs }) => {
  const listRef = useRef<HTMLDivElement>(null);

  // Auto scroll to bottom when new logs arrive
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [logs]);

  // Format timestamp (hh:mm:ss)
  const formatTime = (ts: number) => {
    const d = new Date(ts);
    return d.toTimeString().split(' ')[0];
  };

  return (
    <div className="event-log-container glass-panel">
      <div className="event-log-title">
        <span>Table Logs</span>
        <span style={{ fontSize: '0.65rem', opacity: 0.5 }}>Real-time Feed</span>
      </div>

      <div className="event-logs-list" ref={listRef}>
        {logs.map((log) => {
          let typeLabel = '📣';
          if (log.type === 'action') typeLabel = '🃏';
          else if (log.type === 'win') typeLabel = '🏆';
          else if (log.type === 'chat') typeLabel = '💬';

          return (
            <div key={log.id} className={`log-item ${log.type}`}>
              <span style={{ color: 'rgba(255,255,255,0.3)', marginRight: '6px' }}>
                [{formatTime(log.timestamp)}]
              </span>
              <span style={{ marginRight: '6px' }}>{typeLabel}</span>
              <span>{log.message}</span>
            </div>
          );
        })}
        {logs.length === 0 && (
          <div style={{ color: 'rgba(255,255,255,0.2)', textAlign: 'center', marginTop: '20px' }}>
            No log entries yet.
          </div>
        )}
      </div>
    </div>
  );
};
