import { useState, useEffect } from 'react';
import { useWsData } from '../context/AppContext';

// Events that are too noisy for the default log view
const NOISY_TYPES = new Set(['tick', 'candle', 'book_ticker']);

export default function LogsPage() {
  const wsData = useWsData();
  const [logs, setLogs] = useState([]);
  const [showTicks, setShowTicks] = useState(false);

  // Capture WebSocket events as log entries
  useEffect(() => {
    const handleWs = (e) => {
      const msg = e.detail;
      // Filter out noisy events unless user opts in
      if (!showTicks && NOISY_TYPES.has(msg.type)) return;

      setLogs(prev => [{
        time: new Date().toLocaleTimeString(),
        type: msg.type,
        data: JSON.stringify(msg.data),
      }, ...prev.slice(0, 199)]);
    };

    window.addEventListener('ws_message', handleWs);
    return () => window.removeEventListener('ws_message', handleWs);
  }, [showTicks]);

  return (
    <>
      <div className="page-header">
        <div><h2>Live Logs</h2><div className="subtitle">Real-time WebSocket event stream</div></div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className={`btn btn-sm ${showTicks ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setShowTicks(v => !v)}
          >{showTicks ? '🔊 Ticks ON' : '🔇 Ticks OFF'}</button>
          <button className="btn btn-outline btn-sm" onClick={() => setLogs([])}>Clear</button>
        </div>
      </div>
      <div className="page-content">
        <div className="card" style={{ padding: 0 }}>
          {logs.length === 0 ? (
            <div className="empty-state" style={{ padding: 40 }}>
              <div className="icon">📝</div>
              <h3>Waiting for events…</h3>
              <p>Live events from the engine will appear here. Tick events are hidden by default.</p>
            </div>
          ) : (
            <div style={{ maxHeight: 600, overflowY: 'auto', padding: 4 }}>
              {logs.map((l, i) => (
                <div key={i} style={{
                  display: 'flex', gap: 12, padding: '8px 16px',
                  borderBottom: '1px solid var(--border-primary)',
                  fontFamily: 'var(--font-mono)', fontSize: '0.8rem',
                }}>
                  <span style={{ color: 'var(--text-muted)', flexShrink: 0, width: 70 }}>{l.time}</span>
                  <span className={`badge ${
                    l.type === 'fill' ? 'badge-green' : l.type === 'safety' ? 'badge-red' :
                    l.type.includes('position') ? 'badge-purple' :
                    l.type === 'order_placed' ? 'badge-blue' :
                    l.type === 'order_cancelled' ? 'badge-yellow' :
                    l.type === 'trailing_moved' ? 'badge-blue' :
                    l.type === 'tick' ? '' : 'badge-blue'
                  }`} style={{ flexShrink: 0 }}>{l.type.replace('_', ' ')}</span>
                  <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.data}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
