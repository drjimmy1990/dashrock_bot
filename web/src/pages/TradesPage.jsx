import { useState, useEffect } from 'react';
import { api } from '../services/api';
import { useApp } from '../context/AppContext';

function fmtUsd(n) { return n != null ? `$${Number(n).toFixed(4)}` : '—'; }
function fmtDate(ms) { return ms ? new Date(ms).toLocaleString() : '—'; }

const FILTER_OPTIONS = [
  { label: 'Today', value: 'today' },
  { label: '7 Days', value: '7d' },
  { label: '30 Days', value: '30d' },
  { label: 'All Time', value: 'all' },
];

function getFilterCutoff(filter) {
  const now = Date.now();
  if (filter === 'today') {
    const d = new Date(); d.setHours(0, 0, 0, 0);
    return d.getTime();
  }
  if (filter === '7d') return now - 7 * 86400_000;
  if (filter === '30d') return now - 30 * 86400_000;
  return 0; // all
}

export default function TradesPage() {
  const [allTrades, setAllTrades] = useState([]);
  const [filter, setFilter] = useState('today');
  const [sideFilter, setSideFilter] = useState('all');
  const [resultFilter, setResultFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const { toast } = useApp();

  const fetchTrades = () => {
    setLoading(true);
    api.trades(null, 500).then(setAllTrades).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { fetchTrades(); }, []);

  // Apply filters
  const cutoff = getFilterCutoff(filter);
  const trades = allTrades.filter(t => {
    if (t.exit_time_ms < cutoff) return false;
    if (sideFilter !== 'all' && t.side !== sideFilter) return false;
    if (resultFilter === 'wins' && t.realized_pnl <= 0) return false;
    if (resultFilter === 'losses' && t.realized_pnl > 0) return false;
    return true;
  });

  const totalPnl = trades.reduce((s, t) => s + t.realized_pnl, 0);
  const wins = trades.filter(t => t.realized_pnl > 0).length;
  const losses = trades.filter(t => t.realized_pnl < 0).length;
  const winRate = trades.length > 0 ? ((wins / trades.length) * 100).toFixed(1) : '0';
  const totalFees = trades.reduce((s, t) => s + (t.fees || 0), 0);

  const handleClearHistory = async () => {
    if (!confirm('⚠️ Delete ALL trade history from the database?\n\nThis cannot be undone.')) return;
    try {
      const r = await api.clearTrades();
      toast(r.message || '✅ Trade history cleared');
      setAllTrades([]);
    } catch (e) { toast(e.message, 'error'); }
  };

  const filterBtnStyle = (active) => ({
    padding: '4px 12px', borderRadius: 6, border: '1px solid var(--border-primary)',
    background: active ? 'var(--accent)' : 'transparent',
    color: active ? '#fff' : 'var(--text-muted)',
    cursor: 'pointer', fontSize: '0.78rem', fontWeight: 500, transition: 'all 0.15s',
  });

  return (
    <>
      <div className="page-header">
        <div><h2>Trade History</h2><div className="subtitle">{trades.length} of {allTrades.length} trades shown</div></div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-sm btn-outline" onClick={fetchTrades} disabled={loading}>🔄 Refresh</button>
          <button className="btn btn-sm btn-danger" onClick={handleClearHistory}>🗑 Clear History</button>
        </div>
      </div>
      <div className="page-content">

        {/* ─── Filter Bar ─── */}
        <div className="card" style={{ marginBottom: 16, padding: '12px 16px' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
            {/* Time filter */}
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginRight: 4 }}>📅</span>
              {FILTER_OPTIONS.map(o => (
                <button key={o.value} style={filterBtnStyle(filter === o.value)} onClick={() => setFilter(o.value)}>
                  {o.label}
                </button>
              ))}
            </div>

            {/* Side filter */}
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginRight: 4 }}>📊</span>
              {[{ label: 'All', value: 'all' }, { label: 'Long', value: 'LONG' }, { label: 'Short', value: 'SHORT' }].map(o => (
                <button key={o.value} style={filterBtnStyle(sideFilter === o.value)} onClick={() => setSideFilter(o.value)}>
                  {o.label}
                </button>
              ))}
            </div>

            {/* Result filter */}
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginRight: 4 }}>💰</span>
              {[{ label: 'All', value: 'all' }, { label: 'Wins', value: 'wins' }, { label: 'Losses', value: 'losses' }].map(o => (
                <button key={o.value} style={filterBtnStyle(resultFilter === o.value)} onClick={() => setResultFilter(o.value)}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ─── Stats ─── */}
        <div className="card-grid card-grid-4" style={{ marginBottom: 20 }}>
          <div className="card stat">
            <div className="stat-label">Trades (filtered)</div>
            <div className="stat-value">{trades.length}</div>
          </div>
          <div className="card stat">
            <div className="stat-label">Win Rate</div>
            <div className={`stat-value ${parseFloat(winRate) >= 50 ? 'positive' : 'negative'}`}>{winRate}%</div>
          </div>
          <div className="card stat">
            <div className="stat-label">Net PnL</div>
            <div className={`stat-value ${totalPnl >= 0 ? 'positive' : 'negative'}`}>{fmtUsd(totalPnl)}</div>
          </div>
          <div className="card stat">
            <div className="stat-label">W / L / Fees</div>
            <div className="stat-value">
              <span style={{color:'var(--green)'}}>{wins}</span> / <span style={{color:'var(--red)'}}>{losses}</span>
              <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginLeft: 6 }}>{fmtUsd(totalFees)}</span>
            </div>
          </div>
        </div>

        {/* ─── Table ─── */}
        <div className="card">
          <div className="card-header"><span className="card-title">Trades</span></div>
          {trades.length === 0 ? (
            <div className="empty-state"><div className="icon">📋</div><h3>{allTrades.length > 0 ? 'No trades match filters' : 'No trades yet'}</h3><p>{allTrades.length > 0 ? 'Try changing the time range or filter.' : 'Trades will appear here once the engine executes.'}</p></div>
          ) : (
            <div className="table-wrap" style={{ maxHeight: 500, overflowY: 'auto' }}>
              <table>
                <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>Fees</th><th>Funding</th><th>Exit Reason</th></tr></thead>
                <tbody>
                  {trades.map((t, i) => (
                    <tr key={t.id || i}>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{fmtDate(t.exit_time_ms)}</td>
                      <td style={{ fontWeight: 600 }}>{t.symbol}</td>
                      <td><span className={`badge ${t.side === 'LONG' ? 'badge-green' : 'badge-red'}`}>{t.side}</span></td>
                      <td>{Number(t.entry_price).toFixed(4)}</td>
                      <td>{Number(t.exit_price).toFixed(4)}</td>
                      <td>{Number(t.quantity).toFixed(6)}</td>
                      <td className={t.realized_pnl >= 0 ? 'td-green' : 'td-red'}>{fmtUsd(t.realized_pnl)}</td>
                      <td style={{ color: 'var(--text-muted)' }}>{fmtUsd(t.fees)}</td>
                      <td style={{ color: 'var(--text-muted)' }}>{fmtUsd(t.funding_cost)}</td>
                      <td><span className={`badge ${t.exit_reason === 'tp' ? 'badge-green' : t.exit_reason === 'sl' ? 'badge-red' : 'badge-yellow'}`}>{t.exit_reason}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
