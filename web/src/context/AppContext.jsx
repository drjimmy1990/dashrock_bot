import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api, connectWS } from '../services/api';

const AppCtx = createContext(null);
const WsCtx = createContext(null);

export function AppProvider({ children }) {
  const [token, setToken] = useState(localStorage.getItem('dashrock_token'));
  const [status, setStatus] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [wsData, setWsData] = useState({});

  const login = async (u, p) => {
    const data = await api.login(u, p);
    localStorage.setItem('dashrock_token', data.access_token);
    setToken(data.access_token);
  };

  const logout = () => {
    localStorage.removeItem('dashrock_token');
    setToken(null);
  };

  const toast = useCallback((msg, type = 'success') => {
    const id = Date.now();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  }, []);

  // Poll status every 5s when authenticated
  useEffect(() => {
    if (!token) return;
    const poll = () => api.status().then(setStatus).catch(() => {});
    poll();
    const iv = setInterval(poll, 5000);
    return () => clearInterval(iv);
  }, [token]);

  // WebSocket connection
  useEffect(() => {
    if (!token) return;
    return connectWS((msg) => {
      setWsData(prev => ({ ...prev, [msg.type]: msg.data, _last: msg }));
      if (msg.type === 'position_opened') toast(`📈 ${msg.data.symbol} ${msg.data.side} @ ${msg.data.entry}`, 'success');
      if (msg.type === 'position_closed') {
        const pnl = msg.data.pnl;
        toast(`${pnl >= 0 ? '✅' : '❌'} ${msg.data.symbol} closed — PnL: $${pnl?.toFixed(2)} (${msg.data.reason})`, pnl >= 0 ? 'success' : 'error');
      }
      if (msg.type === 'safety') toast(`⚠️ Safety: ${msg.data.reason}`, 'warning');
    });
  }, [token, toast]);

  return (
    <AppCtx.Provider value={{ token, login, logout, status, toast, toasts }}>
      <WsCtx.Provider value={wsData}>
        {children}
      </WsCtx.Provider>
    </AppCtx.Provider>
  );
}

/** Auth, status, toast — stable, rarely re-renders */
export const useApp = () => useContext(AppCtx);

/** WebSocket live data — updates frequently, only use in pages that need it */
export const useWsData = () => useContext(WsCtx);
