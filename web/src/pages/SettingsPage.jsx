import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { useApp } from '../context/AppContext';

// ─── Stable components (defined OUTSIDE SettingsPage to prevent remount flicker) ───

function Section({ title, children }) {
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-header"><span className="card-title">{title}</span></div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12, padding: '0 16px 16px' }}>
        {children}
      </div>
    </div>
  );
}

function Field({ label, hint, path, type = 'text', options, draft, update }) {
  const keys = path.split('.');
  let val = draft;
  for (const k of keys) val = val?.[k];

  if (type === 'toggle') return (
    <div>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      {hint && <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', opacity: 0.6, marginBottom: 4 }}>{hint}</div>}
      <button
        className={`btn btn-sm ${val ? 'btn-primary' : 'btn-outline'}`}
        onClick={() => update(path, !val)}
        style={{ width: '100%' }}
      >{val ? 'ON' : 'OFF'}</button>
    </div>
  );

  if (type === 'select') return (
    <div>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      {hint && <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', opacity: 0.6, marginBottom: 4 }}>{hint}</div>}
      <select
        value={val || ''}
        onChange={e => update(path, e.target.value)}
        style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-primary)', background: 'var(--bg-input)', color: 'var(--text-primary)', fontSize: '0.88rem' }}
      >
        {(options || []).map(o => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
      </select>
    </div>
  );

  return (
    <div>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      {hint && <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', opacity: 0.6, marginBottom: 4 }}>{hint}</div>}
      <input
        type={type === 'number' ? 'number' : 'text'}
        value={val ?? ''}
        onChange={e => update(path, type === 'number' ? parseFloat(e.target.value) || 0 : e.target.value)}
        step={type === 'number' ? 'any' : undefined}
        style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-primary)', background: 'var(--bg-input)', color: 'var(--text-primary)', fontSize: '0.88rem', fontFamily: 'var(--font-mono)' }}
      />
    </div>
  );
}

/** Editable tag list for watchlist / trade_list arrays */
function TagListField({ label, hint, path, draft, update }) {
  const keys = path.split('.');
  let items = draft;
  for (const k of keys) items = items?.[k];
  items = items || [];

  const [input, setInput] = useState('');

  const addItem = () => {
    const sym = input.trim().toUpperCase();
    if (!sym || items.includes(sym)) return;
    update(path, [...items, sym]);
    setInput('');
  };

  const removeItem = (sym) => {
    update(path, items.filter(s => s !== sym));
  };

  return (
    <div style={{ gridColumn: '1 / -1' }}>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      {hint && <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', opacity: 0.6, marginBottom: 4 }}>{hint}</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
        {items.map(sym => (
          <span key={sym} style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '4px 10px', borderRadius: 16,
            background: 'rgba(99,102,241,0.15)', color: '#818cf8',
            fontSize: '0.82rem', fontWeight: 600,
          }}>
            {sym}
            <button onClick={() => removeItem(sym)} style={{
              background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer',
              fontSize: '0.9rem', padding: 0, lineHeight: 1,
            }}>×</button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addItem()}
          placeholder="e.g. ETHUSDT"
          style={{ flex: 1, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border-primary)', background: 'var(--bg-input)', color: 'var(--text-primary)', fontSize: '0.82rem' }}
        />
        <button className="btn btn-sm btn-outline" onClick={addItem}>+ Add</button>
      </div>
    </div>
  );
}

// ─── Position Mode Toggle (Binance One-Way vs Hedge) ───

function PositionModeToggle({ toast }) {
  const [hedgeMode, setHedgeMode] = useState(null);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [source, setSource] = useState('');

  useEffect(() => {
    api.positionMode()
      .then(d => { setHedgeMode(d.hedge_mode); setSource(d.source); })
      .catch(() => setHedgeMode(null))
      .finally(() => setLoading(false));
  }, []);

  const toggle = async () => {
    const newMode = !hedgeMode;
    const label = newMode ? 'Hedge Mode' : 'One-Way Mode';
    if (!confirm(`Switch to ${label}?\n\n⚠️ This requires NO open positions or orders on Binance.\nThis applies to ALL symbols globally.`)) return;

    setSwitching(true);
    try {
      const res = await api.setPositionMode(newMode);
      setHedgeMode(res.hedge_mode);
      toast(`✅ ${res.message}`);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSwitching(false);
    }
  };

  if (loading) return <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Loading position mode…</div>;
  if (hedgeMode === null) return null;

  return (
    <div style={{ gridColumn: '1 / -1' }}>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 2 }}>Binance Position Mode</div>
      <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', opacity: 0.6, marginBottom: 6 }}>
        One-Way = single direction per symbol. Hedge = hold LONG + SHORT simultaneously.
        {source === 'simulator' && ' (Simulated — no exchange call)'}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          className={`btn btn-sm ${!hedgeMode ? 'btn-primary' : 'btn-outline'}`}
          onClick={() => hedgeMode && toggle()}
          disabled={switching || !hedgeMode}
          style={{ flex: 1 }}
        >
          One-Way
        </button>
        <button
          className={`btn btn-sm ${hedgeMode ? 'btn-primary' : 'btn-outline'}`}
          onClick={() => !hedgeMode && toggle()}
          disabled={switching || hedgeMode}
          style={{ flex: 1 }}
        >
          Hedge
        </button>
      </div>
      {switching && <div style={{ fontSize: '0.72rem', color: '#f59e0b', marginTop: 4 }}>⏳ Switching…</div>}
    </div>
  );
}

// ─── Main Settings Page ─────────────────────────────────────

export default function SettingsPage() {
  const [cfg, setCfg] = useState(null);
  const [draft, setDraft] = useState({});
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { toast } = useApp();

  useEffect(() => {
    api.config().then(d => { setCfg(d); setDraft(d); }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const update = useCallback((path, value) => {
    setDraft(prev => {
      const copy = structuredClone(prev);
      const keys = path.split('.');
      let obj = copy;
      for (let i = 0; i < keys.length - 1; i++) obj = obj[keys[i]];
      obj[keys[keys.length - 1]] = value;
      return copy;
    });
    setDirty(true);
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateConfig(draft);
      setCfg(draft);
      setDirty(false);
      toast('✅ Settings saved & applied to running engine');
    } catch (e) { toast(e.message, 'error'); }
    finally { setSaving(false); }
  };

  const handleReset = async () => {
    if (!confirm('⚠️ This will wipe ALL trading data and reset the engine. Are you sure?')) return;
    try { const r = await api.reset(); toast(r.message, 'warning'); }
    catch (e) { toast(e.message, 'error'); }
  };

  if (loading || !cfg || !draft) return <div className="page-content"><div className="empty-state"><h3>Loading config…</h3></div></div>;

  return (
    <>
      <div className="page-header">
        <div><h2>Settings</h2><div className="subtitle">{dirty ? '● Unsaved changes' : 'Engine configuration — changes apply immediately on save'}</div></div>
        <div style={{ display: 'flex', gap: 8 }}>
          {dirty && <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>{saving ? '⏳ Saving…' : '💾 Save & Apply'}</button>}
          <button className="btn btn-danger btn-sm" onClick={handleReset}>🗑 Factory Reset</button>
        </div>
      </div>
      <div className="page-content">

        {/* ─── General ─── */}
        <Section title="🌐 General">
          <Field label="Mode" hint="paper = simulated, testnet = Binance testnet, live = real money"
            path="mode" type="select"
            options={[
              { value: 'paper', label: 'Paper (simulated)' },
              { value: 'testnet', label: 'Testnet' },
              { value: 'live', label: 'Live (real $)' },
            ]}
            draft={draft} update={update} />
          <Field label="Timeframe" hint="Candle interval — strategy recomputes every candle close"
            path="timeframe" type="select"
            options={['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d']}
            draft={draft} update={update} />
          <TagListField label="🔫 Trade List" hint="Symbols the engine actively trades — WS streams connect for these only"
            path="trade_list" draft={draft} update={update} />
          <TagListField label="🔍 Watchlist" hint="Symbols scanned for opportunities — scanner uses REST API (no WS). Must include all trade_list symbols."
            path="watchlist" draft={draft} update={update} />
        </Section>

        {/* ─── Strategy ─── */}
        <Section title="📊 Strategy">
          <Field label="Strategy Name" hint="Only donchian_breakout is available"
            path="strategy.name" type="select" options={['donchian_breakout']}
            draft={draft} update={update} />
          <Field label="Lookback Candles" hint="Number of candles to find Highest High / Lowest Low (2–500)"
            path="strategy.lookback_candles" type="number"
            draft={draft} update={update} />
          <Field label="Offset %" hint="Buffer above HH / below LL to avoid false breakouts"
            path="strategy.offset_pips" type="number"
            draft={draft} update={update} />
          <Field label="Refresh Mode" hint="How pending orders update each candle"
            path="strategy.pending_refresh_mode" type="select"
            options={[
              { value: 'dynamic', label: 'Dynamic — levels move every candle' },
              { value: 'fixed', label: 'Fixed — levels lock on first calculation' },
              { value: 'hybrid_tighter', label: 'Hybrid — levels can only tighten' },
            ]}
            draft={draft} update={update} />
          <Field label="Cooldown Candles" hint="Wait N candles after a position closes before re-entering"
            path="strategy.cooldown_candles" type="number"
            draft={draft} update={update} />
          <Field label="Cooldown Trigger" hint="What triggers the cooldown period"
            path="strategy.cooldown_trigger" type="select"
            options={[
              { value: 'any_close', label: 'Any Close — after any position close' },
              { value: 'sl_only', label: 'SL Only — only after stop loss hits' },
              { value: 'after_fill', label: 'After Fill — after any order fills' },
            ]}
            draft={draft} update={update} />
          <Field label="Min Channel Width %" hint="Skip if HH-LL spread is too narrow (no room for SL)"
            path="strategy.min_channel_width_pct" type="number"
            draft={draft} update={update} />
          <Field label="Use Pct Pips" hint="If ON, offset/SL/TP are treated as percentages, not absolute pips"
            path="strategy.use_pct_pips" type="toggle"
            draft={draft} update={update} />
        </Section>

        {/* ─── Regime Detection ─── */}
        <Section title="🧠 Regime Detection">
          <Field label="Enabled" hint="Skip ranging markets — only trade when trend is strong"
            path="strategy.regime_detection.enabled" type="toggle"
            draft={draft} update={update} />
          <Field label="Method" hint="How market regime is classified"
            path="strategy.regime_detection.method" type="select"
            options={[
              { value: 'adx', label: 'ADX — trend strength' },
              { value: 'bollinger_squeeze', label: 'Bollinger Squeeze' },
              { value: 'both', label: 'Both — ADX + Bollinger' },
            ]}
            draft={draft} update={update} />
          <Field label="ADX Period" hint="Lookback for ADX calculation (default 14)"
            path="strategy.regime_detection.adx_period" type="number"
            draft={draft} update={update} />
          <Field label="ADX Trending Threshold" hint="ADX above this = trending market (default 25)"
            path="strategy.regime_detection.adx_trending_threshold" type="number"
            draft={draft} update={update} />
          <Field label="Skip Ranging" hint="If ON, skip all entries when market is ranging"
            path="strategy.regime_detection.skip_ranging" type="toggle"
            draft={draft} update={update} />
        </Section>

        {/* ─── Sizing & Risk ─── */}
        <Section title="💰 Sizing & Risk">
          <Field label="Sizing Mode" hint="How position size is calculated"
            path="sizing.mode" type="select"
            options={[
              { value: 'risk_per_trade', label: 'Risk % per trade' },
              { value: 'fixed', label: 'Fixed USD amount' },
              { value: 'equity_fraction', label: 'Fraction of equity' },
            ]}
            draft={draft} update={update} />
          <Field label="Risk per Trade %" hint="% of equity risked on each trade (0.01–10)"
            path="sizing.risk_per_trade_pct" type="number"
            draft={draft} update={update} />
          <Field label="Leverage" hint="Position leverage multiplier (1–125)"
            path="sizing.leverage" type="number"
            draft={draft} update={update} />
          <Field label="Fallback Fixed $" hint="Fixed USD size when sizing mode = 'fixed'"
            path="sizing.fallback_fixed_usd" type="number"
            draft={draft} update={update} />
          <Field label="Max Open Positions" hint="Maximum simultaneous positions across all symbols"
            path="portfolio_risk.max_open_positions" type="number"
            draft={draft} update={update} />
          <Field label="Max Total Exposure %" hint="Total notional value as % of equity (300 = 3x)"
            path="portfolio_risk.max_total_exposure_pct" type="number"
            draft={draft} update={update} />
          <Field label="Max Per-Symbol Exposure %" hint="Max notional for a single symbol as % of equity"
            path="portfolio_risk.max_per_symbol_exposure_pct" type="number"
            draft={draft} update={update} />
        </Section>

        {/* ─── Equity ─── */}
        <Section title="🏦 Equity Source">
          <Field label="Source" hint="auto = read from exchange API, manual = use fixed value below"
            path="equity.source" type="select"
            options={[
              { value: 'auto', label: 'Auto — from exchange API' },
              { value: 'manual', label: 'Manual — fixed value' },
            ]}
            draft={draft} update={update} />
          <Field label="Manual Value $" hint="Used when source=manual"
            path="equity.manual_value" type="number"
            draft={draft} update={update} />
        </Section>

        {/* ─── Stops & Trailing ─── */}
        <Section title="🛑 Stops & Trailing">
          <Field label="Stop Loss %" hint="Distance from entry to SL as % of price"
            path="stops.sl_pips" type="number"
            draft={draft} update={update} />
          <Field label="Take Profit %" hint="Distance from entry to TP as % of price. 0 = no TP"
            path="stops.tp_pips" type="number"
            draft={draft} update={update} />
          <Field label="Use Pct Pips (Stops)" hint="If ON, SL/TP values are percentages. OFF = absolute pips."
            path="stops.use_pct_pips" type="toggle"
            draft={draft} update={update} />
          <Field label="Trailing Enabled" hint="Ratchet SL in your favor as price moves"
            path="trailing.enabled" type="toggle"
            draft={draft} update={update} />
          <Field label="Trailing Mode" hint="Step = fixed increments, Activation = after profit threshold"
            path="trailing.mode" type="select"
            options={[
              { value: 'step', label: 'Step — move SL every N%' },
              { value: 'activation_trail', label: 'Activation — trail after profit %' },
              { value: 'off', label: 'Off — no trailing' },
            ]}
            draft={draft} update={update} />
          <Field label="Trailing Step %" hint="SL moves up by this % each step"
            path="trailing.step_pips" type="number"
            draft={draft} update={update} />
          <Field label="Trailing Stop %" hint="Distance behind price for trailing SL"
            path="trailing.stop_pips" type="number"
            draft={draft} update={update} />
          <Field label="Trailing Activation %" hint="Profit needed before trailing starts"
            path="trailing.activation_pips" type="number"
            draft={draft} update={update} />
          <Field label="Use Pct Pips (Trailing)" hint="If ON, trailing values are percentages."
            path="trailing.use_pct_pips" type="toggle"
            draft={draft} update={update} />
        </Section>

        {/* ─── Opposite Order ─── */}
        <Section title="🔄 On Fill: Opposite Order">
          <Field label="Mode" hint="What happens to the other side's stop order when one fills"
            path="reversed_order.mode" type="select"
            options={[
              { value: 'cancel', label: 'Cancel — delete opposite order' },
              { value: 'keep_reverse', label: 'Keep & Reverse — flip position' },
              { value: 'keep_close_only', label: 'Keep (close only) — exits but no new position' },
              { value: 'hedge', label: 'Hedge — keep both open (Requires Hedge Mode)' },
            ]}
            draft={draft} update={update} />
        </Section>

        {/* ─── Spread & Slippage ─── */}
        <Section title="📏 Spread & Slippage Guard">
          <Field label="Max Spread (pips)" hint="Reject entries if spread exceeds this"
            path="spread.max_pips" type="number"
            draft={draft} update={update} />
          <Field label="Use Dynamic Spread" hint="Use ATR-based dynamic spread threshold"
            path="spread.use_dynamic" type="toggle"
            draft={draft} update={update} />
          <Field label="Dynamic ATR Multiplier" hint="Spread threshold = ATR × this value"
            path="spread.dynamic_atr_mult" type="number"
            draft={draft} update={update} />
          <Field label="Log Only" hint="If ON, wide spread is logged but trades still execute"
            path="spread.log_only" type="toggle"
            draft={draft} update={update} />
          <Field label="Max Slippage %" hint="Alert or close if fill slippage exceeds this"
            path="slippage.max_pct" type="number"
            draft={draft} update={update} />
          <Field label="On Slippage Violation" hint="What to do when slippage exceeds max"
            path="slippage.on_violation" type="select"
            options={[
              { value: 'alert', label: 'Alert — log & notify only' },
              { value: 'close_immediately', label: 'Close — exit position immediately' },
            ]}
            draft={draft} update={update} />
        </Section>

        {/* ─── Safety ─── */}
        <Section title="🛡️ Safety">
          <Field label="Max Daily Loss %" hint="Circuit breaker: pause trading after this daily loss"
            path="safety.max_daily_loss_pct" type="number"
            draft={draft} update={update} />
          <Field label="Max Drawdown %" hint="Halt trading if equity drops this much from peak"
            path="safety.max_drawdown_pct" type="number"
            draft={draft} update={update} />
          <Field label="Max Consec. Losses" hint="Pause after N consecutive losing trades"
            path="safety.max_consecutive_losses" type="number"
            draft={draft} update={update} />
          <Field label="Check on Tick" hint="Run safety checks on every price tick (not just candle close)"
            path="safety.check_on_tick" type="toggle"
            draft={draft} update={update} />
          <Field label="Tick Check Interval" hint="Check safety every N ticks (lower = more responsive but heavier)"
            path="safety.tick_check_interval" type="number"
            draft={draft} update={update} />
          <Field label="Orphan Order Policy" hint="What to do with orders that have no matching position"
            path="safety.orphan_order_policy" type="select"
            options={[
              { value: 'alert_only', label: 'Alert Only — log & notify' },
              { value: 'cancel', label: 'Cancel — auto-cancel orphans' },
            ]}
            draft={draft} update={update} />
        </Section>

        {/* ─── Volatility Scanner ─── */}
        <Section title="🔬 Volatility Scanner">
          <Field label="Mode" hint="Scoring method for watchlist symbols"
            path="volatility.mode" type="select"
            options={[
              { value: 'normalized_atr', label: 'Normalized ATR' },
              { value: 'composite', label: 'Composite (NATR + Expansion + Donchian)' },
            ]}
            draft={draft} update={update} />
          <Field label="Min Score" hint="Minimum volatility score to qualify (0–1)"
            path="volatility.min_score" type="number"
            draft={draft} update={update} />
          <Field label="Min 24h Volume $" hint="Skip symbols below this 24h USD volume"
            path="volatility.min_24h_volume_usd" type="number"
            draft={draft} update={update} />
        </Section>

        {/* ─── Simulator ─── */}
        <Section title="🧪 Simulator (Paper Mode Only)">
          <Field label="Starting Equity $" hint="Simulated account balance for paper trading"
            path="simulator.starting_equity_usd" type="number"
            draft={draft} update={update} />
          <Field label="Taker Fee %" hint="Simulated exchange fee per fill (Binance = 0.04%)"
            path="simulator.taker_fee_pct" type="number"
            draft={draft} update={update} />
          <Field label="Slippage Noise %" hint="Random slippage added to simulated fills"
            path="simulator.slippage_noise_pips" type="number"
            draft={draft} update={update} />
          <Field label="Simulate Funding" hint="Charge simulated funding rate every 8 hours"
            path="simulator.simulate_funding" type="toggle"
            draft={draft} update={update} />
          <Field label="Funding Rate %" hint="Funding cost per 8h period (Binance avg = 0.01%)"
            path="simulator.funding_rate_pct" type="number"
            draft={draft} update={update} />
          <Field label="Latency (ms)" hint="Simulated order placement delay (0 = instant)"
            path="simulator.latency_ms" type="number"
            draft={draft} update={update} />
        </Section>

        {/* ─── Logging ─── */}
        <Section title="📝 Logging">
          <Field label="Log Level" hint="Verbosity of backend logs"
            path="logging.level" type="select"
            options={['DEBUG', 'INFO', 'WARNING', 'ERROR']}
            draft={draft} update={update} />
        </Section>

        {/* ─── Live Trading ─── */}
        {(draft?.mode === 'live' || draft?.mode === 'testnet') && (
          <Section title="🔴 Live Trading">
            <PositionModeToggle toast={toast} />
            <Field label="Auto-Set Leverage" hint="Automatically configure leverage on Binance at startup"
              path="live.auto_set_leverage" type="toggle"
              draft={draft} update={update} />
            <Field label="Auto-Set Margin Type" hint="Automatically set margin type per symbol"
              path="live.auto_set_margin_type" type="toggle"
              draft={draft} update={update} />
            <Field label="Margin Type" hint="ISOLATED limits loss to position; CROSSED uses full balance"
              path="live.margin_type" type="select"
              options={[
                { value: 'ISOLATED', label: 'Isolated (Safer)' },
                { value: 'CROSSED', label: 'Crossed (Full Balance)' },
              ]}
              draft={draft} update={update} />
            <Field label="Recv Window (ms)" hint="Maximum time for request to reach Binance (default 5000)"
              path="live.recv_window_ms" type="number"
              draft={draft} update={update} />
            <Field label="Listen Key Refresh (sec)" hint="How often to refresh UserData WS key (default 1800)"
              path="live.listen_key_refresh_sec" type="number"
              draft={draft} update={update} />
            <Field label="Startup Reconciliation" hint="Compare exchange state with DB on every restart"
              path="live.startup_reconcile" type="toggle"
              draft={draft} update={update} />
            <Field label="Max Retries" hint="Number of retry attempts for failed API calls"
              path="live.max_retries" type="number"
              draft={draft} update={update} />
          </Section>
        )}

      </div>
    </>
  );
}
