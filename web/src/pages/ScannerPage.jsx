import { useState } from 'react';
import { api } from '../services/api';
import { useApp } from '../context/AppContext';

export default function ScannerPage() {
  const [results, setResults] = useState([]);
  const [scanning, setScanning] = useState(false);
  const { toast } = useApp();

  const runScan = async () => {
    setScanning(true);
    try {
      const data = await api.scan();
      setResults(data.results || []);
      toast(`Scanned ${data.ranked} symbols`);
    } catch (e) { toast(e.message, 'error'); }
    finally { setScanning(false); }
  };

  return (
    <>
      <div className="page-header">
        <div><h2>Volatility Scanner</h2><div className="subtitle">Rank symbols by breakout potential</div></div>
        <button className="btn btn-primary btn-sm" onClick={runScan} disabled={scanning}>
          {scanning ? '⏳ Scanning…' : '🔍 Run Scan'}
        </button>
      </div>
      <div className="page-content">
        <div className="card">
          {results.length === 0 ? (
            <div className="empty-state">
              <div className="icon">🔍</div>
              <h3>No scan results</h3>
              <p>Click "Run Scan" to rank symbols by volatility score.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>Symbol</th><th>Score</th><th>NATR %</th><th>Bar</th></tr></thead>
                <tbody>
                  {results.map((r, i) => {
                    const pct = Math.min((r.score / (results[0]?.score || 1)) * 100, 100);
                    return (
                      <tr key={r.symbol}>
                        <td style={{ color: 'var(--text-muted)' }}>{i + 1}</td>
                        <td style={{ fontWeight: 600 }}>{r.symbol}</td>
                        <td>{r.score.toFixed(4)}</td>
                        <td>{r.natr.toFixed(3)}%</td>
                        <td style={{ width: '40%' }}>
                          <div style={{ background: 'var(--bg-input)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
                            <div style={{
                              width: `${pct}%`, height: '100%',
                              background: `linear-gradient(90deg, var(--accent), var(--purple))`,
                              borderRadius: 4, transition: 'width 0.5s ease',
                            }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
