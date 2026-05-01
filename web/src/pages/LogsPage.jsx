import { useState, useEffect, useRef, useSyncExternalStore } from 'react';
import { useWsData } from '../context/AppContext';

// Events that are too noisy for the default log view
const NOISY_TYPES = new Set(['tick', 'candle', 'book_ticker', 'equity']);
const MAX_LOGS = 500;

// ─── Window-level log store (survives HMR + navigation + refresh) ───
const STORAGE_KEY = 'dashrock_logs';

function _loadFromStorage() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function _saveToStorage(logs) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(logs)); } catch {}
}

if (!window.__dr_logs) {
  window.__dr_logs = _loadFromStorage();
  window.__dr_listeners = new Set();
  window.__dr_wsAttached = false;
}

function _notify() {
  window.__dr_listeners.forEach(fn => fn());
}

function addLog(entry) {
  window.__dr_logs = [entry, ...window.__dr_logs.slice(0, MAX_LOGS - 1)];
  _saveToStorage(window.__dr_logs);
  _notify();
}

function clearLogs() {
  window.__dr_logs = [];
  _saveToStorage(window.__dr_logs);
  _notify();
}

function subscribe(listener) {
  window.__dr_listeners.add(listener);
  return () => window.__dr_listeners.delete(listener);
}

function getSnapshot() {
  return window.__dr_logs;
}

// Format timestamp — use server time (timestamp_ms) when available
function formatTime(data) {
  const ts = data?.timestamp_ms || data?.ts;
  if (ts && ts > 1000000000000) {
    return new Date(ts).toLocaleTimeString('en-GB', { hour12: false });
  }
  return new Date().toLocaleTimeString('en-GB', { hour12: false });
}

// ─── Global WS listener (attached ONCE on window, survives HMR) ───
if (!window.__dr_wsAttached) {
  window.__dr_wsAttached = true;
  window.addEventListener('ws_message', (e) => {
    const msg = e.detail;
    if (NOISY_TYPES.has(msg.type)) return; // noisy events handled by tick listener below
    addLog({
      time: formatTime(msg.data),
      type: msg.type,
      data: JSON.stringify(msg.data),
    });
  });
}

export default function LogsPage() {
  const wsData = useWsData();
  const wsStatus = wsData?._wsStatus || 'connecting';
  const logs = useSyncExternalStore(subscribe, getSnapshot);
  const [showTicks, setShowTicks] = useState(false);
  const showTicksRef = useRef(showTicks);
  showTicksRef.current = showTicks;

  // Separate tick listener (only captures ticks when toggle is ON)
  useEffect(() => {
    const handleTick = (e) => {
      const msg = e.detail;
      if (!NOISY_TYPES.has(msg.type)) return;
      if (!showTicksRef.current) return;
      addLog({
        time: formatTime(msg.data),
        type: msg.type,
        data: JSON.stringify(msg.data),
      });
    };
    window.addEventListener('ws_message', handleTick);
    return () => window.removeEventListener('ws_message', handleTick);
  }, []);

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
          <button className="btn btn-outline btn-sm" onClick={clearLogs}>Clear</button>
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
                    l.type === 'native_trailing' ? 'badge-purple' :
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
