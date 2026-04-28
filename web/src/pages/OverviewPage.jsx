import { useState, useEffect } from 'react';
import { api } from '../services/api';
import { useApp, useWsData } from '../context/AppContext';

function fmt(n, d = 2) { return n != null ? Number(n).toFixed(d) : '—'; }
function fmtUsd(n) { return n != null ? `$${Number(n).toFixed(2)}` : '—'; }

export default function OverviewPage() {
  const { toast, status } = useApp();
  const wsData = useWsData();
  const [equity, setEquity] = useState(null);
  const [pnl, setPnl] = useState(null);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);

  const refresh = async () => {
    try {
      const [eq, p, pos, ord] = await Promise.all([api.equity(), api.pnl(), api.positions(), api.orders()]);
      setEquity(eq.equity_usd);
      setPnl(p);
      setPositions(pos);
      setOrders(ord);
    } catch {} finally { setLoading(false); }
  };

  useEffect(() => { refresh(); const iv = setInterval(refresh, 5000); return () => clearInterval(iv); }, []);

  const handleAction = async (action, label) => {
    setActionLoading(action);
    try {
      let r;
      if (action === 'close_all') {
        if (!confirm('Close ALL positions and cancel ALL orders?')) { setActionLoading(null); return; }
        r = await api.closeAll();
        toast(`Cancelled ${r.cancelled_orders} orders, closed ${r.closed_positions} positions`);
      } else if (action === 'pause') {
        r = await api.pause();
        toast(r.message);
      } else if (action === 'resume') {
        r = await api.resume();
        toast(r.message);
      } else if (action === 'scan') {
        r = await api.scan();
        toast(`Scanned ${r.ranked} symbols`);
      }
      refresh();
    } catch (e) { toast(e.message, 'error'); }
    finally { setActionLoading(null); }
  };

  const equityFromWs = wsData?.equity?.equity ?? equity;
  const isRunning = status?.engine_state === 'running';
  const isPaused = status?.engine_state === 'paused';
  const mode = status?.mode || 'paper';

  const isLive = mode === 'live';
  const isTestnet = mode === 'testnet';

  return (
    <>
      {isLive && (
        <div style={{
          background: 'linear-gradient(90deg, #dc2626 0%, #991b1b 100%)',
          color: '#fff',
          padding: '10px 20px',
          borderRadius: 8,
          marginBottom: 16,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          fontWeight: 600,
          fontSize: 14,
        }}>
          <span style={{ fontSize: 20 }}>⚠️</span>
          LIVE TRADING — Real money is at risk. Kill switch is available below.
        </div>
      )}
      <div className="page-header">
        <div>
          <h2>Overview</h2>
          <div className="subtitle">
            <span className={`badge ${isRunning ? 'badge-green' : isPaused ? 'badge-yellow' : 'badge-blue'}`} style={{ marginRight: 8 }}>
              {status?.engine_state?.toUpperCase() || 'LOADING'}
            </span>
            <span className={`badge ${isLive ? 'badge-red' : isTestnet ? 'badge-yellow' : 'badge-purple'}`}>
              {mode.toUpperCase()}
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {(!isRunning) && (
            <button className="btn btn-primary btn-sm" onClick={() => handleAction('resume')} disabled={actionLoading === 'resume'}>
              {actionLoading === 'resume' ? '⏳…' : '▶ Start Trading'}
            </button>
          )}
          {isRunning && (
            <button className="btn btn-outline btn-sm" onClick={() => handleAction('pause')} disabled={actionLoading === 'pause'}>
              {actionLoading === 'pause' ? '⏳…' : '⏸ Pause Trading'}
            </button>
          )}
          <button className="btn btn-outline btn-sm" onClick={() => handleAction('scan')} disabled={actionLoading === 'scan'}>
            {actionLoading === 'scan' ? '⏳…' : '🔍 Scan'}
          </button>
          <button className="btn btn-danger btn-sm" onClick={() => handleAction('close_all')} disabled={actionLoading === 'close_all'}>
            {actionLoading === 'close_all' ? '⏳…' : '⏹ Kill Switch'}
          </button>
        </div>
      </div>
      <div className="page-content">
        {/* Stats Row */}
        <div className="card-grid card-grid-4" style={{ marginBottom: 20 }}>
          <div className="card stat">
            <div className="stat-label">Equity</div>
            <div className="stat-value">{fmtUsd(equityFromWs)}</div>
          </div>
          <div className="card stat">
            <div className="stat-label">Today's PnL</div>
            <div className={`stat-value ${(pnl?.realized_pnl_today || 0) >= 0 ? 'positive' : 'negative'}`}>
              {fmtUsd(pnl?.realized_pnl_today)}
            </div>
          </div>
          <div className="card stat">
            <div className="stat-label">High Water</div>
            <div className="stat-value">{fmtUsd(pnl?.equity_high_water)}</div>
          </div>
          <div className="card stat">
            <div className="stat-label">Consec. Losses</div>
            <div className={`stat-value ${(pnl?.consecutive_losses || 0) >= 3 ? 'negative' : ''}`}>
              {pnl?.consecutive_losses ?? '—'}
            </div>
          </div>
        </div>

        {/* Open Positions */}
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header">
            <span className="card-title">Open Positions</span>
            <span className="badge badge-blue">{positions.length}</span>
          </div>
          {positions.length === 0 ? (
            <div className="empty-state"><div className="icon">📭</div><h3>No open positions</h3><p>The strategy will open positions when breakout signals fire.</p></div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Mark</th><th>uPnL</th><th>SL</th><th>TP</th><th>Trail</th></tr></thead>
                <tbody>
                  {positions.map(p => (
                    <tr key={p.symbol}>
                      <td style={{ fontWeight: 600 }}>{p.symbol}</td>
                      <td><span className={`badge ${p.side === 'LONG' ? 'badge-green' : 'badge-red'}`}>{p.side}</span></td>
                      <td>{fmt(p.quantity, 6)}</td>
                      <td>{fmt(p.entry_price, 4)}</td>
                      <td>{fmt(p.mark_price, 4)}</td>
                      <td className={p.unrealized_pnl >= 0 ? 'td-green' : 'td-red'}>{fmtUsd(p.unrealized_pnl)}</td>
                      <td>{fmt(p.sl_price, 4)}</td>
                      <td>{fmt(p.tp_price, 4)}</td>
                      <td>{p.trailing_active ? <span className="badge badge-purple">ACTIVE</span> : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Pending Orders */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Pending Orders</span>
            <span className="badge badge-yellow">{orders.length}</span>
          </div>
          {orders.length === 0 ? (
            <div className="empty-state"><div className="icon">📋</div><h3>No pending orders</h3><p>Stop orders will appear here when the strategy places them.</p></div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Type</th><th>Stop Price</th><th>Qty</th><th>Tag</th></tr></thead>
                <tbody>
                  {orders.map(o => (
                    <tr key={o.order_id}>
                      <td style={{ color: 'var(--text-muted)' }}>{o.order_id}</td>
                      <td style={{ fontWeight: 600 }}>{o.symbol}</td>
                      <td><span className={`badge ${o.side === 'BUY' ? 'badge-green' : 'badge-red'}`}>{o.side}</span></td>
                      <td>{o.order_type}</td>
                      <td>{fmt(o.stop_price, 4)}</td>
                      <td>{fmt(o.quantity, 6)}</td>
                      <td><span className="badge badge-blue">{o.tag}</span></td>
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
