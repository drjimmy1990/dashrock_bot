import { NavLink } from 'react-router-dom';
import { useApp } from '../context/AppContext';

const NAV = [
  { to: '/', icon: '📊', label: 'Overview' },
  { to: '/chart', icon: '📈', label: 'Chart' },
  { to: '/trades', icon: '📋', label: 'Trades' },
  { to: '/scanner', icon: '🔍', label: 'Scanner' },
  { to: '/settings', icon: '⚙️', label: 'Settings' },
  { to: '/logs', icon: '📝', label: 'Logs' },
];

export default function Sidebar() {
  const { status, logout } = useApp();
  const engineState = status?.engine_state || 'unknown';
  const dotClass = ['running'].includes(engineState) ? 'running'
    : ['paused', 'ready'].includes(engineState) ? 'paused'
    : ['error'].includes(engineState) ? 'error' : 'stopped';

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <h1>Dashrock</h1>
        <span className="version">v2</span>
      </div>
      <nav className="sidebar-nav">
        {NAV.map(n => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => isActive ? 'active' : ''} end={n.to === '/'}>
            <span>{n.icon}</span> {n.label}
          </NavLink>
        ))}
        <button onClick={logout} style={{ marginTop: 'auto' }}>
          <span>🚪</span> Logout
        </button>
      </nav>
      <div className="sidebar-status">
        <div className="status-pill">
          <span className={`status-dot ${dotClass}`} />
          <span style={{ textTransform: 'capitalize' }}>{engineState}</span>
          {status?.mode && <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: '0.78rem' }}>{status.mode}</span>}
        </div>
      </div>
    </aside>
  );
}
