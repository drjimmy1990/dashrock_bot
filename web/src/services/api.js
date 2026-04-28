const API_BASE = import.meta.env.VITE_API_URL || '';

function getToken() {
  return localStorage.getItem('dashrock_token');
}

async function request(path, options = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    localStorage.removeItem('dashrock_token');
    window.location.reload();
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export const api = {
  login: (u, p) => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: u, password: p }) }),
  health: () => request('/api/health'),
  status: () => request('/api/status'),
  config: () => request('/api/config'),
  updateConfig: (d) => request('/api/config', { method: 'PUT', body: JSON.stringify(d) }),
  equity: () => request('/api/equity'),
  equityHistory: (l = 100) => request(`/api/equity/history?limit=${l}`),
  trades: (s, l = 50) => request(`/api/trades?${s ? `symbol=${s}&` : ''}limit=${l}`),
  positions: () => request('/api/positions/open'),
  orders: () => request('/api/orders/open-all'),
  pnl: () => request('/api/pnl/today'),
  closeAll: () => request('/api/close-all', { method: 'POST' }),
  pause: () => request('/api/pause', { method: 'POST' }),
  resume: () => request('/api/resume', { method: 'POST' }),
  reset: () => request('/api/reset', { method: 'POST' }),
  scan: () => request('/api/scan', { method: 'POST' }),
  candles: (s, l = 200) => request(`/api/candles/${s}?limit=${l}`),
  levels: (s) => request(`/api/levels/${s}`),
  watchlist: () => request('/api/watchlist'),
  positionMode: () => request('/api/position-mode'),
  setPositionMode: (hedge) => request('/api/position-mode', { method: 'POST', body: JSON.stringify({ hedge_mode: hedge }) }),
  clearTrades: () => request('/api/trades', { method: 'DELETE' }),
};

export function connectWS(onMessage) {
  const token = getToken();
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const isDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  const wsHost = isDev ? '127.0.0.1:8000' : window.location.host;
  const wsUrl = `${proto}://${wsHost}/ws?token=${token || ''}`;
  let ws, reconnectTimer, disposed = false;
  let backoff = 2000;
  const maxBackoff = 30000;

  function connect() {
    if (disposed) return;
    try {
      ws = new WebSocket(wsUrl);
      ws.onopen = () => { console.log('[WS] Connected'); backoff = 2000; };
      ws.onmessage = (e) => { 
        try { 
          const msg = JSON.parse(e.data);
          onMessage(msg); 
          window.dispatchEvent(new CustomEvent('ws_message', { detail: msg }));
        } catch {} 
      };
      ws.onclose = () => {
        if (!disposed) {
          reconnectTimer = setTimeout(connect, backoff);
          backoff = Math.min(backoff * 1.5, maxBackoff);
        }
      };
      ws.onerror = () => { try { ws.close(); } catch {} };
    } catch {
      if (!disposed) reconnectTimer = setTimeout(connect, backoff);
    }
  }
  connect();
  return () => { disposed = true; clearTimeout(reconnectTimer); try { ws?.close(); } catch {} };
}
