import { useState, useEffect, useRef } from 'react';
import { useWsData } from '../context/AppContext';

// Events that are too noisy for the default log view
const NOISY_TYPES = new Set(['tick', 'candle', 'book_ticker']);

export default function LogsPage() {
  const wsData = useWsData();
  const wsStatus = wsData?._wsStatus || 'connecting';
  const [logs, setLogs] = useState([]);
  const [showTicks, setShowTicks] = useState(false);
  const showTicksRef = useRef(showTicks);
  showTicksRef.current = showTicks;

  // Listen to global WS CustomEvents (fired by api.js connectWS)
  useEffect(() => {
    const handleWs = (e) => {
      const msg = e.detail;
      // Filter out noisy events unless user opts in (use ref for latest value)
      if (!showTicksRef.current && NOISY_TYPES.has(msg.type)) return;

      setLogs(prev => [{
        time: new Date().toLocaleTimeString(),
        type: msg.type,
        data: JSON.stringify(msg.data),
      }, ...prev.slice(0, 499)]);
    };

    window.addEventListener('ws_message', handleWs);
    return () => window.removeEventListener('ws_message', handleWs);
  }, []); // Only once — showTicksRef handles the toggle

  const statusColor = wsStatus === 'connected' ? 'var(--color-green)' :
                       wsStatus === 'auth_failed' ? 'var(--color-red)' : 'var(--color-yellow)';

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Live Logs</h2>
          <div className="subtitle" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            Real-time WebSocket event stream
            <span style={{
              display: 'inline-block', width: 8, height: 8,
              borderRadius: '50%', background: statusColor,
            }} title={`WS: ${wsStatus}`} />
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{wsStatus}</span>
          </div>
        </div>
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
              {wsStatus === 'auth_failed' && (
                <p style={{ color: 'var(--color-red)' }}>⚠️ WebSocket auth failed. Try logging out and back in.</p>
              )}
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
