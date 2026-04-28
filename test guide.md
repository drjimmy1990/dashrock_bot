# Dashrock v2 — End-to-End Test Guide

> **Goal**: Verify every layer of the system works correctly, from unit tests through API to the dashboard UI.

---

## Phase 1: Prerequisites & Environment Setup

### 1.1 — Verify Python Installation

```powershell
C:\Python313\python.exe --version
```

> [!IMPORTANT]
> **Expected**: `Python 3.13.x`

### 1.2 — Install Dependencies

```powershell
cd c:\Users\LOQ\dashrock-v2
C:\Python313\python.exe -m pip install -e ".[dev]"
```

> **Expected**: `Successfully installed dashrock-v2-2.0.0` (and all dependencies)

### 1.3 — Create `.env` File

```powershell
cd c:\Users\LOQ\dashrock-v2
copy .env.example .env
```

Edit `.env` with your values:

```env
# For paper mode testing, DB is required. Get URL from Supabase:
# Project → Settings → Database → Connection String → URI
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.YOUR_REF.supabase.co:5432/postgres

# Auth credentials for the dashboard
JWT_SECRET=test-secret-key-change-in-production
ADMIN_USERNAME=admin
ADMIN_PASSWORD=test123

# Leave empty for now (paper mode doesn't need these)
BINANCE_API_KEY=
BINANCE_API_SECRET=
```

### 1.4 — Install Dashboard Dependencies

```powershell
cd c:\Users\LOQ\dashrock-v2\web
npm install
```

> **Expected**: `found 0 vulnerabilities`

---

## Phase 2: Automated Tests (No DB Required)

These tests run entirely in-memory using the simulator and fake repo.

### 2.1 — Run All 12 Integration Tests

```powershell
cd c:\Users\LOQ\dashrock-v2
C:\Python313\python.exe -m pytest tests/test_integration.py -v --tb=short
```

> [!IMPORTANT]
> **Expected**: All 12 tests pass
> ```
> test_config_loads PASSED
> test_state_machine PASSED
> test_strategy_compute PASSED
> test_strategy_regime_skip PASSED
> test_position_sizer PASSED
> test_portfolio_risk PASSED
> test_safety_monitor PASSED
> test_simulator_fill_cycle PASSED
> test_execution_manager_entry_exit PASSED
> test_symbol_registry PASSED
> test_spread_guard PASSED
> test_event_bus_sync PASSED
> ====== 12 passed ======
> ```

### What Each Test Verifies

| # | Test | What It Proves |
|---|------|----------------|
| 1 | `test_config_loads` | `config.yaml` → Pydantic validation works, all sections parse |
| 2 | `test_state_machine` | FSM transitions: init → ready → running → paused → resumed → stopped. Invalid transitions are blocked |
| 3 | `test_strategy_compute` | Donchian breakout produces buy/sell stop orders from trending candle data |
| 4 | `test_strategy_regime_skip` | ADX regime detection correctly blocks signals in flat/ranging markets |
| 5 | `test_position_sizer` | Risk-per-trade math: 1% of $1000 = $10 risk ÷ 75 SL distance = 0.1333 BTC |
| 6 | `test_portfolio_risk` | Max positions limit blocks new entries when 2/2 slots are filled |
| 7 | `test_safety_monitor` | Daily loss circuit breaker triggers at 6% (> 5% limit), passes at 1% |
| 8 | `test_simulator_fill_cycle` | Place stop order → price tick below → no fill → tick above → fill fires |
| 9 | `test_execution_manager_entry_exit` | **Full lifecycle**: strategy signal → entry order → fill → SL/TP placed → SL hit → position closed → PnL recorded |
| 10 | `test_symbol_registry` | Default symbol loading, quantity rounding (floors, never rounds up), min notional validation |
| 11 | `test_spread_guard` | Static spread threshold: 3 pips < 5 max → pass; 10 pips > 5 max → block |
| 12 | `test_event_bus_sync` | EventBus handlers execute in subscription order (backpressure verified) |

### 2.2 — Build Dashboard (Compile Check)

```powershell
cd c:\Users\LOQ\dashrock-v2\web
npx vite build
```

> **Expected**: `✓ built in XXms` with 0 errors, 40 modules transformed

---

## Phase 3: Engine Startup (Requires Supabase DB)

> [!WARNING]
> From here on, you need a working `DATABASE_URL` in your `.env` file. If you don't have Supabase yet, create a free project at [supabase.com](https://supabase.com).

### 3.1 — Start the Engine

Open **Terminal 1**:

```powershell
cd c:\Users\LOQ\dashrock-v2
C:\Python313\python.exe -m dashrock run --port 8000
```

> **Expected console output** (in order):
> ```
> Database connected and tables verified
> Simulator started — equity=$1000.00, fee=0.0400%, slippage=0.0100%
> Auth configured for user: admin
> Engine RUNNING. API at http://0.0.0.0:8000
> ```

> [!IMPORTANT]
> **Checklist — verify these in the console:**
> - [ ] "Database connected and tables verified" — DB is reachable
> - [ ] "Simulator started" — Paper adapter initialized
> - [ ] "Auth configured" — JWT is working
> - [ ] "Engine RUNNING" — All components wired, main loop started
> - [ ] No Python tracebacks or error logs

### 3.2 — Verify Database Tables Were Created

Go to your **Supabase Dashboard → Table Editor**. You should see **8 tables**:

| Table | Purpose |
|-------|---------|
| `trades` | Completed trade records |
| `orders` | Order audit log |
| `equity_snapshots` | Equity curve data |
| `engine_state` | Per-symbol execution state (crash recovery) |
| `event_log` | System event audit trail |
| `scanner_snapshots` | Volatility scan results |
| `config_overrides` | Runtime config changes |
| `funding_rates` | Funding rate history |

> **Pass criteria**: All 8 tables exist and are empty

---

## Phase 4: API Endpoint Testing

With the engine running on port 8000, open **Terminal 2** and test each endpoint.

### 4.1 — Health Check (No Auth Required)

```powershell
curl http://localhost:8000/api/health
```

> **Expected**:
> ```json
> {"status":"healthy","engine_state":"running","db_connected":true,"ws_connected":true,"uptime_seconds":...}
> ```

- [ ] `engine_state` = `"running"`
- [ ] `db_connected` = `true`

### 4.2 — Login (Get JWT Token)

```powershell
$body = '{"username":"admin","password":"test123"}'
$response = Invoke-RestMethod -Uri http://localhost:8000/api/auth/login -Method POST -Body $body -ContentType "application/json"
$TOKEN = $response.access_token
Write-Host "TOKEN: $TOKEN"
```

> **Expected**: A long JWT string like `eyJhbGciOiJIUzI1Ni...`

- [ ] Token is returned (not empty)
- [ ] `token_type` = `"bearer"`

### 4.3 — Test Invalid Login (Should Fail)

```powershell
$body = '{"username":"admin","password":"wrong"}'
Invoke-RestMethod -Uri http://localhost:8000/api/auth/login -Method POST -Body $body -ContentType "application/json"
```

> **Expected**: 401 error `"Invalid credentials"`

### 4.4 — Test Protected Route Without Token

```powershell
curl http://localhost:8000/api/status
```

> **Expected**: 403 Forbidden (no Bearer token)

### 4.5 — Status (Authenticated)

```powershell
$headers = @{ Authorization = "Bearer $TOKEN" }
Invoke-RestMethod -Uri http://localhost:8000/api/status -Headers $headers
```

> **Expected**:
> ```json
> {"engine_state":"running","mode":"paper","is_running":true,"restart_required":false}
> ```

### 4.6 — Get Equity

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/equity -Headers $headers
```

> **Expected**: `{"equity_usd": 1000.0}` (starting equity from config)

### 4.7 — Get Watchlist

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/watchlist -Headers $headers
```

> **Expected**: `{"symbols":["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","DOGEUSDT"],"timeframe":"1m"}`

### 4.8 — Get Config

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/config -Headers $headers
```

> **Expected**: Full config object with all sections (strategy, sizing, stops, trailing, safety, etc.)

### 4.9 — Get Open Positions

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/positions/open -Headers $headers
```

> **Expected**: Empty array `[]` (no positions yet in paper mode)

### 4.10 — Get Open Orders

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/orders/open-all -Headers $headers
```

> **Expected**: Array of pending stop orders (buy stop + sell stop per traded symbol)

### 4.11 — Get Today's PnL

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/pnl/today -Headers $headers
```

> **Expected**: `{"realized_pnl_today":0.0,"equity_high_water":...,"consecutive_losses":0}`

### 4.12 — Get Trade History

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/trades -Headers $headers
```

> **Expected**: Empty array `[]` (no trades yet)

### 4.13 — Get Candles

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/candles/BTCUSDT?limit=5" -Headers $headers
```

> **Expected**: Array of OHLC objects (may be empty in paper mode without live feed)

### 4.14 — Run Scanner

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/scan -Method POST -Headers $headers
```

> **Expected**: `{"ranked": N, "results": [...]}` with volatility scores

### 4.15 — Resume Trading

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/resume -Method POST -Headers $headers
```

> **Expected**: `{"message":"Resumed. Placed orders for N symbols."}`

### 4.16 — Close All (Kill Switch)

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/close-all -Method POST -Headers $headers
```

> **Expected**: `{"cancelled_orders":N,"closed_positions":0}`

### 4.17 — Factory Reset

> [!CAUTION]
> This wipes ALL trading data from the database.

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/reset -Method POST -Headers $headers
```

> **Expected**: `{"message":"All data cleared. Engine paused."}`

### API Test Summary Checklist

| # | Endpoint | Method | Auth | Status |
|---|----------|--------|------|--------|
| 1 | `/api/health` | GET | ❌ | ☐ |
| 2 | `/api/auth/login` | POST | ❌ | ☐ |
| 3 | `/api/auth/login` (bad pw) | POST | ❌ | ☐ |
| 4 | `/api/status` (no token) | GET | ❌ | ☐ |
| 5 | `/api/status` | GET | ✅ | ☐ |
| 6 | `/api/equity` | GET | ✅ | ☐ |
| 7 | `/api/watchlist` | GET | ✅ | ☐ |
| 8 | `/api/config` | GET | ✅ | ☐ |
| 9 | `/api/positions/open` | GET | ✅ | ☐ |
| 10 | `/api/orders/open-all` | GET | ✅ | ☐ |
| 11 | `/api/pnl/today` | GET | ✅ | ☐ |
| 12 | `/api/trades` | GET | ✅ | ☐ |
| 13 | `/api/candles/BTCUSDT` | GET | ✅ | ☐ |
| 14 | `/api/scan` | POST | ✅ | ☐ |
| 15 | `/api/resume` | POST | ✅ | ☐ |
| 16 | `/api/close-all` | POST | ✅ | ☐ |
| 17 | `/api/reset` | POST | ✅ | ☐ |

---

## Phase 5: Dashboard UI Testing

### 5.1 — Start the Dashboard

Open **Terminal 3** (keep engine running in Terminal 1):

```powershell
cd c:\Users\LOQ\dashrock-v2\web
npm run dev
```

Open browser at **http://localhost:5173**

### 5.2 — Login Page

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Page loads | Gradient background, "Dashrock" title, username/password fields | ☐ |
| 2 | Empty submit | No crash, may show error | ☐ |
| 3 | Wrong password | Red error: "Invalid credentials" | ☐ |
| 4 | Correct login (`admin` / `test123`) | Redirects to Overview page | ☐ |
| 5 | Refresh after login | Stays logged in (token in localStorage) | ☐ |

### 5.3 — Sidebar Navigation

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Logo & version | "Dashrock" gradient text + "v2" badge | ☐ |
| 2 | Navigation links | 📊 Overview, 📈 Chart, 📋 Trades, 🔍 Scanner, ⚙️ Settings, 📝 Logs | ☐ |
| 3 | Active link highlight | Current page link is blue/highlighted | ☐ |
| 4 | Engine status pill | Bottom of sidebar shows "running" with green pulsing dot | ☐ |
| 5 | Mode label | Shows "paper" next to status | ☐ |
| 6 | Logout button | Click → returns to login page | ☐ |

### 5.4 — Overview Page

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Stats row | 4 cards: Equity ($1000), Today's PnL ($0), High Water, Consec. Losses | ☐ |
| 2 | Equity value | Shows `$1000.00` (paper starting equity) | ☐ |
| 3 | PnL color | Green when ≥ 0, Red when < 0 | ☐ |
| 4 | Open Positions table | Empty state: "📭 No open positions" | ☐ |
| 5 | Pending Orders table | Shows buy/sell stop orders with correct tags | ☐ |
| 6 | Kill Switch button | Red "⏹ Kill Switch" in header | ☐ |
| 7 | Kill Switch click | Confirmation dialog → cancels all orders → toast notification | ☐ |
| 8 | Resume button | "▶ Resume" appears when engine is paused | ☐ |
| 9 | Resume click | Toast: "Resumed. Placed orders for N symbols." | ☐ |
| 10 | Auto-refresh | Data refreshes every 5 seconds (check equity/orders update) | ☐ |

### 5.5 — Chart Page

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Chart renders | Dark candlestick chart with green/red candles | ☐ |
| 2 | Symbol selector | Buttons: BTC, ETH, SOL, BNB, DOGE | ☐ |
| 3 | Switch symbol | Click different symbol → chart reloads with new data | ☐ |
| 4 | Active symbol highlight | Selected button is blue, others are outline | ☐ |
| 5 | Chart resize | Window resize → chart adjusts width | ☐ |
| 6 | Crosshair | Hover on chart → shows price/time crosshair | ☐ |

### 5.6 — Trades Page

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Stats row | 4 cards: Total Trades, Win Rate, Net PnL, W/L ratio | ☐ |
| 2 | Empty state | "📋 No trades yet" message | ☐ |
| 3 | After some trades | Table shows: Time, Symbol, Side, Entry, Exit, Qty, PnL, Fees, Funding, Exit Reason | ☐ |
| 4 | PnL coloring | Green for wins, red for losses | ☐ |
| 5 | Side badges | Green "LONG" / Red "SHORT" badges | ☐ |
| 6 | Exit reason badges | Green "tp" / Red "sl" / Yellow for others | ☐ |

### 5.7 — Scanner Page

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Empty state | "🔍 No scan results" | ☐ |
| 2 | Run Scan button | Click → button shows "⏳ Scanning…" → results appear | ☐ |
| 3 | Results table | Columns: #, Symbol, Score, NATR %, Bar (gradient progress) | ☐ |
| 4 | Sorted by score | Highest volatility symbol first | ☐ |
| 5 | Toast notification | "Scanned N symbols" after completion | ☐ |

### 5.8 — Settings Page

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Config sections | General, Strategy, Sizing & Risk, Stops, Safety | ☐ |
| 2 | General section | Mode: paper, Timeframe: 1m, Watchlist, Trade List | ☐ |
| 3 | Strategy section | Name: donchian_breakout, Lookback: 10, Offset: 0.05% | ☐ |
| 4 | Sizing section | Mode: risk_per_trade, Risk/Trade: 1%, Leverage: 10x | ☐ |
| 5 | Safety section | Max Daily Loss: 5%, Max Drawdown: 15%, Max Consec: 5 | ☐ |
| 6 | Factory Reset button | Red "🗑 Factory Reset" → confirmation → wipes data | ☐ |

### 5.9 — Logs Page

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Empty state | "📝 Waiting for events…" | ☐ |
| 2 | Live events | Events appear as the engine runs (tick, candle, fill, etc.) | ☐ |
| 3 | Color coding | Green for fills, Purple for positions, Red for safety, Blue for others | ☐ |
| 4 | Timestamp | Each event shows HH:MM:SS timestamp | ☐ |
| 5 | Clear button | Click → all logs cleared | ☐ |
| 6 | Max 200 entries | Oldest events drop off when > 200 | ☐ |

### 5.10 — Toast Notifications

| # | Test | Expected | ☐ |
|---|------|----------|---|
| 1 | Position opened | "📈 BTCUSDT BUY @ ..." toast with green border | ☐ |
| 2 | Position closed (win) | "✅ BTCUSDT closed — PnL: $X.XX (tp)" green toast | ☐ |
| 3 | Position closed (loss) | "❌ BTCUSDT closed — PnL: -$X.XX (sl)" red toast | ☐ |
| 4 | Safety triggered | "⚠️ Safety: ..." yellow toast | ☐ |
| 5 | Auto-dismiss | Toasts disappear after ~4 seconds | ☐ |

---

## Phase 6: Stress & Edge Case Tests

### 6.1 — Crash Recovery

```
1. Start engine → let it run for ~1 minute
2. Kill the process (Ctrl+C or close terminal)
3. Check Supabase → engine_state table should have saved states
4. Restart the engine
5. Check logs → "Restored execution state for N symbols"
6. Verify positions/orders are consistent with pre-crash state
```

- [ ] States saved to DB on shutdown
- [ ] States restored on restart
- [ ] No orphan orders after restart

### 6.2 — Auth Token Expiry

```
1. Login → get token
2. Wait (or set token_expiry_hours: 1 in config, then wait)
3. Try an authenticated endpoint
4. Expected: 401 Unauthorized → dashboard should redirect to login
```

### 6.3 — Safety Circuit Breaker

Edit `config.yaml`:

```yaml
safety:
  max_daily_loss_pct: 0.01  # Very low threshold
```

```
1. Restart engine with the low threshold
2. Let it trade until a loss occurs
3. Expected: "SAFETY TRIGGERED" in logs
4. Expected: Engine pauses, no new entries
5. Expected: Dashboard shows safety toast notification
```

### 6.4 — Kill Switch Under Load

```
1. Wait until there are open positions + pending orders
2. Click "⏹ Kill Switch" on the dashboard
3. Expected: All orders cancelled, all positions closed
4. Expected: Toast shows cancelled/closed counts
5. Expected: Overview refreshes to show empty tables
```

### 6.5 — Factory Reset

```
1. Let engine trade for a while (accumulate trades, snapshots)
2. Go to Settings → click "🗑 Factory Reset"
3. Confirm the dialog
4. Expected: All DB tables are emptied
5. Expected: Equity resets to $1000
6. Expected: Engine pauses
7. Click Resume → engine starts fresh
```

### 6.6 — Multiple Browser Tabs

```
1. Open dashboard in 2 browser tabs
2. Both should show same data
3. Click Kill Switch in Tab 1
4. Tab 2 should receive WebSocket events and update
```

---

## Final Verification Checklist

| Area | Tests | Status |
|------|-------|--------|
| **Unit Tests** | 12/12 pytest tests pass | ☐ |
| **Dashboard Build** | `vite build` succeeds with 0 errors | ☐ |
| **Engine Startup** | Connects to DB, creates 8 tables, starts simulator | ☐ |
| **Auth** | Login works, bad creds rejected, token protects routes | ☐ |
| **17 API Endpoints** | All return correct responses (see Phase 4 checklist) | ☐ |
| **Dashboard Login** | Renders, validates, redirects correctly | ☐ |
| **Dashboard Overview** | Equity, positions, orders, kill switch all work | ☐ |
| **Dashboard Chart** | TradingView renders, symbol switch works | ☐ |
| **Dashboard Trades** | Stats + table display correctly | ☐ |
| **Dashboard Scanner** | Run scan produces ranked results | ☐ |
| **Dashboard Settings** | All config values displayed correctly | ☐ |
| **Dashboard Logs** | Live events stream with correct badges | ☐ |
| **WebSocket** | Live toasts for position open/close/safety | ☐ |
| **Crash Recovery** | State persisted + restored on restart | ☐ |
| **Safety Monitor** | Circuit breaker triggers at threshold | ☐ |
| **Kill Switch** | Cancels all orders + closes positions | ☐ |
| **Factory Reset** | Wipes DB and resets equity | ☐ |
