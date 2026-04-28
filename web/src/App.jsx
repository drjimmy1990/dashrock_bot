import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { AppProvider, useApp } from './context/AppContext';
import LoginPage from './pages/LoginPage';
import OverviewPage from './pages/OverviewPage';
import ChartPage from './pages/ChartPage';
import TradesPage from './pages/TradesPage';
import ScannerPage from './pages/ScannerPage';
import SettingsPage from './pages/SettingsPage';
import LogsPage from './pages/LogsPage';
import Sidebar from './components/Sidebar';

function DashboardLayout() {
  return (
    <div className="app-layout">
      <Sidebar />
      <main className="main-area">
        <Outlet />
      </main>
    </div>
  );
}

function ProtectedRoute() {
  const { token } = useApp();
  return token ? <DashboardLayout /> : <Navigate to="/login" replace />;
}

function AppRoutes() {
  const { token, toasts } = useApp();
  return (
    <>
      <Routes>
        <Route path="/login" element={token ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/chart" element={<ChartPage />} />
          <Route path="/trades" element={<TradesPage />} />
          <Route path="/scanner" element={<ScannerPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      {/* Toast notifications */}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.type}`}>{t.msg}</div>
        ))}
      </div>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <AppRoutes />
      </AppProvider>
    </BrowserRouter>
  );
}
