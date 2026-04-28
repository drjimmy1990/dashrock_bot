# Dashrock Bot v2 — Rebuild Implementation Plan

## My Recommendation: Full Rebuild

> [!IMPORTANT]
> **I recommend a full rebuild from scratch**, reusing only the _design patterns_ (not code) from v1.

**Why not modify?**
- `main.py` is a 380-line god function — restructuring it means rewriting 80% of the file anyway
- Moving from SQLite → PostgreSQL changes the entire data layer
- Adding state persistence requires redesigning `ExecutionManager` internals
- Swapping `python-binance` (deprecated) → official Binance SDK changes every adapter
- Adding pluggable strategies needs an interface that doesn't exist
- Adding API auth touches every endpoint

Modifying would take longer than rebuilding because you'd spend more time untangling the existing spaghetti than writing clean code. The total source is only ~3,200 lines — this is a small project.

**What we keep (as design inspiration):**
- Adapter pattern (Simulator/Live/Testnet behind an interface) ✅
- Config system (Pydantic models with YAML loading) ✅
- EventBus pattern (pub/sub for decoupling) ✅
- REST API + WebSocket architecture ✅
- Existing React dashboard (update API contracts only) ✅

---

## Binance SDK Decision

> [!IMPORTANT]
> `python-binance` (sammchardy) is **deprecated and being discontinued**.

**New official SDK**: `binance-sdk-derivatives-trading-usds-futures`
- Published by Binance themselves
- Supports REST API, WebSocket API, and WebSocket Streams
- Has built-in rate limit tracking (`response.rate_limits`)
- Typed enums for order sides, types
- Active maintenance

```bash
pip install binance-sdk-derivatives-trading-usds-futures
```

---

## Architecture v2

```
dashrock-bot/
├── config.yaml
├── .env
├── alembic/                          # [NEW] DB migrations
│   ├── alembic.ini
│   └── versions/
├── src/dashrock/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py                        # [NEW] Application class (replaces god function)
│   ├── config.py                     # [REBUILD] Pydantic config models
│   │
│   ├── core/                         # [NEW] Core domain
│   │   ├── __init__.py
│   │   ├── types.py                  # Domain types (Candle, Order, Position, Fill)
│   │   ├── events.py                 # EventBus + event payloads
│   │   └── state_machine.py          # [NEW] Engine state machine (INIT→READY→RUNNING→PAUSED→STOPPED)
│   │
│   ├── strategy/                     # [NEW] Pluggable strategy system
│   │   ├── __init__.py
│   │   ├── base.py                   # Strategy ABC interface
│   │   ├── donchian_breakout.py      # Current strategy as a plugin
│   │   ├── registry.py              # Strategy loader/registry
│   │   └── indicators.py            # Technical indicator library
│   │
│   ├── execution/                    # [REBUILD] Execution engine
│   │   ├── __init__.py
│   │   ├── manager.py               # Order lifecycle (with state persistence)
│   │   ├── trailing.py              # [NEW] Separated trailing stop logic
│   │   ├── cooldown.py              # [NEW] Separated cooldown logic
│   │   └── opposite_order.py        # [NEW] Separated opposite order policy
│   │
│   ├── risk/                         # [NEW] Proper risk management
│   │   ├── __init__.py
│   │   ├── position_sizer.py        # Risk-per-trade sizing
│   │   ├── portfolio.py             # Max exposure, correlation limits
│   │   └── safety.py                # Circuit breakers (real-time)
│   │
│   ├── market/                       # [REBUILD] Market data
│   │   ├── __init__.py
│   │   ├── data_service.py          # Candle windows + multi-TF support
│   │   ├── funding.py               # [NEW] Funding rate tracker
│   │   └── scanner.py               # Volatility scanner
│   │
│   ├── adapters/                     # [REBUILD] Exchange adapters
│   │   ├── __init__.py
│   │   ├── base.py                  # ABC interface (expanded)
│   │   ├── simulator.py             # Improved paper trading
│   │   ├── binance_live.py          # [NEW] Official SDK adapter
│   │   └── binance_testnet.py       # [NEW] Official SDK testnet
│   │
│   ├── persistence/                  # [NEW] Data layer
│   │   ├── __init__.py
│   │   ├── database.py              # PostgreSQL via asyncpg
│   │   ├── models.py                # SQLAlchemy models
│   │   ├── repositories.py          # Data access layer
│   │   ├── state_store.py           # [NEW] Engine state persistence
│   │   └── config_store.py          # Config overrides
│   │
│   ├── api/                          # [REBUILD] REST + WS API
│   │   ├── __init__.py
│   │   ├── app.py                   # FastAPI app factory
│   │   ├── auth.py                  # [NEW] JWT authentication
│   │   ├── deps.py                  # Dependency injection
│   │   ├── middleware.py            # [NEW] Rate limiting, logging
│   │   ├── routes/                  # [NEW] Organized route modules
│   │   │   ├── status.py
│   │   │   ├── config.py
│   │   │   ├── trading.py
│   │   │   ├── data.py
│   │   │   └── admin.py
│   │   ├── schemas.py               # [NEW] Pydantic response models
│   │   └── ws.py                    # WebSocket manager
│   │
│   ├── notifications/                # [REBUILD] Notifications
│   │   ├── __init__.py
│   │   ├── notifier.py              # Telegram + Discord
│   │   └── templates.py             # [NEW] Message templates
│   │
│   └── utils/                        # [NEW] Shared utilities
│       ├── __init__.py
│       ├── logger.py                # Structured logging
│       ├── time_filter.py           # Session/blackout windows
│       └── reconciliation.py        # Order reconciliation
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py                  # Shared fixtures
│
└── web/                              # Existing React dashboard (update API calls)
```

---

## Phase Breakdown

### Phase 1: Foundation (Core + Config + Types + DB)

> Goal: Establish the skeleton, database, and type system.

#### [NEW] `src/dashrock/core/types.py`
- All domain types: `Candle`, `OrderIntent`, `LiveOrder`, `Position`, `Fill`, `BookTop`, `DesiredOrders`
- Add `TradeRecord` (replaces loose dicts)
- Add `EngineMode` enum: `PAPER | TESTNET | LIVE`
- Add `PositionState` enum: `FLAT | LONG | SHORT`

#### [NEW] `src/dashrock/core/state_machine.py`
- Engine states: `INITIALIZING → READY → RUNNING → PAUSED → STOPPED → ERROR`
- Transition guards (e.g., can't go PAUSED → RUNNING without resume logic)
- State change callbacks (for logging, notifications)

#### [REBUILD] `src/dashrock/config.py`
- Keep all existing Pydantic models (they're good)
- Add `AuthCfg` (jwt_secret, token_expiry)
- Add `DatabaseCfg` (postgres_url, pool_size)
- Add `StrategyPluginCfg` (name, params dict)
- Remove duplicate definitions
- Remove unused `pandas`/`pandas-ta` from dependencies

#### [NEW] `src/dashrock/persistence/models.py`
- SQLAlchemy models for all 6 tables + new tables:
  - `engine_state` — persisted execution state per symbol
  - `funding_rates` — funding rate history
- Proper indexes on timestamp columns

#### [NEW] `src/dashrock/persistence/database.py`
- asyncpg connection pool
- Async context manager for transactions
- Connection health checks

#### [NEW] `alembic/` migration system
- Initial migration creates all tables
- Future schema changes tracked properly

---

### Phase 2: Adapters + Market Data (Binance SDK Migration)

> Goal: Replace python-binance with official SDK, add reconnection.

#### [NEW] `src/dashrock/adapters/binance_live.py`
```python
# Uses: binance-sdk-derivatives-trading-usds-futures
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    ConfigurationRestAPI,
    ConfigurationWebSocketStreams,
)
```
- `place_order()` — uses `client.rest_api.new_order()`
- `cancel_order()` — uses `client.rest_api.cancel_order()`
- `get_position()` — uses `client.rest_api.position_information()`
- `get_equity()` — uses `client.rest_api.account_balance()`
- Built-in rate limit tracking via `response.rate_limits`
- User data stream via WebSocket for fill detection

#### [REBUILD] `src/dashrock/adapters/simulator.py`
- Fix missing `Candle` import
- Add funding rate simulation (configurable 8h interval)
- Track and report simulated funding charges in PnL
- Add latency simulation option (configurable delay before fill callback)

#### [REBUILD] `src/dashrock/market/data_service.py`
- Auto-reconnection with exponential backoff for WebSocket streams
- Multi-timeframe support: maintain separate candle windows per timeframe
- Configurable window sizes per timeframe
- Heartbeat monitoring (detect stale connections)

#### [NEW] `src/dashrock/market/funding.py`
- Poll funding rate from Binance REST API every 8 hours
- Expose current funding rate per symbol
- Calculate funding cost for open positions
- Include funding in PnL calculations

---

### Phase 3: Execution Engine + Risk Management

> Goal: Robust order lifecycle with state persistence and proper risk sizing.

#### [REBUILD] `src/dashrock/execution/manager.py`
**Key Changes:**
- `_SymbolState` persisted to PostgreSQL `engine_state` table on every change
- On startup: restore state from DB, reconcile with exchange
- Cache SL price in `_SymbolState` instead of querying adapter every tick (fixes W-22)
- Emit `PositionOpened`/`PositionClosed` events to EventBus (fixes W-36)
- Call `notifier.send()` on trade events (fixes W-36)

#### [NEW] `src/dashrock/execution/trailing.py`
- Extract trailing stop logic from execution.py (was 150 lines mixed in)
- `StepTrailer` and `ActivationTrailer` classes
- Read cached SL price from state, not from adapter API
- Unit-testable in isolation

#### [NEW] `src/dashrock/risk/position_sizer.py`
```python
def size_for_risk(
    equity: float,
    risk_pct: float,        # e.g., 1% of equity per trade
    entry_price: float,
    sl_price: float,
    leverage: int,
) -> float:
    """Size position so SL hit = risk_pct of equity lost."""
    risk_amount = equity * (risk_pct / 100)
    sl_distance = abs(entry_price - sl_price)
    if sl_distance == 0:
        return 0
    qty = risk_amount / sl_distance
    return qty  # This is the position SIZE, not margin
```

#### [NEW] `src/dashrock/risk/portfolio.py`
- `max_open_positions: int` — cap simultaneous positions
- `max_total_exposure_pct: float` — cap total leveraged notional as % of equity
- `max_per_symbol_exposure_pct: float` — cap single-symbol exposure
- Checked before every `apply_desired()` call

#### [REBUILD] `src/dashrock/risk/safety.py`
- **Real-time checks on every tick** (not just candle close)
- Throttle: check every N ticks (configurable, e.g., every 100 ticks)
- Add funding rate cost to daily PnL calculation
- Emit `SafetyTriggered` event to EventBus + notifier

---

### Phase 4: Strategy System + Regime Detection

> Goal: Pluggable strategies, keep Donchian as first plugin, add regime detection.

#### [NEW] `src/dashrock/strategy/base.py`
```python
from abc import ABC, abstractmethod

class Strategy(ABC):
    """Interface for pluggable trading strategies."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def compute(
        self,
        symbol: str,
        candles: dict[str, list[Candle]],  # timeframe -> candles
        position: PositionState,
    ) -> DesiredOrders: ...

    @abstractmethod
    def on_fill(self, symbol: str, fill: Fill) -> None: ...

    def required_timeframes(self) -> list[str]:
        """Which timeframes this strategy needs data for."""
        return ["1m"]
```

#### [NEW] `src/dashrock/strategy/donchian_breakout.py`
- Port existing Donchian logic as a `Strategy` plugin
- Keep all existing parameters (lookback, offset, refresh mode, min channel width)
- Accept multi-TF candles (use primary TF for signals)

#### [NEW] `src/dashrock/strategy/registry.py`
```python
class StrategyRegistry:
    _strategies: dict[str, type[Strategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_cls: type[Strategy]):
        cls._strategies[name] = strategy_cls

    @classmethod
    def create(cls, name: str, params: dict) -> Strategy:
        return cls._strategies[name](**params)
```

#### Market Regime Detection (as config option)
Add to `StrategyCfg`:
```yaml
strategy:
  regime_detection:
    enabled: true
    method: adx           # adx | bollinger_squeeze | both
    adx_period: 14
    adx_trending_threshold: 25    # ADX > 25 = trending
    skip_ranging: true             # Skip entries when ranging detected
```

Implemented in `indicators.py`:
- `adx(candles, period)` — Average Directional Index
- `bollinger_bandwidth(candles, period, std_dev)` — Bollinger Band width as squeeze detector

---

### Phase 5: API Security + Production Hardening

> Goal: Secure the API, add health checks, improve logging.

#### [NEW] `src/dashrock/api/auth.py`
- JWT token authentication
- Login endpoint (`POST /api/auth/login` with username/password from config)
- Token refresh endpoint
- All other endpoints require valid Bearer token
- WebSocket auth via query parameter token

#### [NEW] `src/dashrock/api/schemas.py`
- Pydantic response models for every endpoint
- OpenAPI docs auto-generated
- Proper error response schema

#### [NEW] `src/dashrock/api/middleware.py`
- Request rate limiting (per IP)
- Request/response logging with correlation IDs
- Error handling middleware (consistent error format)

#### [NEW] Health Check
```python
@router.get("/health")
async def health() -> dict:
    return {
        "status": "healthy",
        "engine_state": state_machine.current_state,
        "db_connected": await db.is_connected(),
        "ws_connected": market_data.is_connected(),
        "uptime_seconds": time.time() - start_time,
    }
```

#### Graceful Shutdown
- Signal handlers for SIGTERM/SIGINT
- On shutdown: persist all `_SymbolState` to DB
- Cancel open entry orders (keep SL/TP alive)
- Log shutdown reason
- Close DB connections cleanly

---

### Phase 6: Dashboard Updates + Final Polish

> Goal: Update React dashboard for new API contracts, add auth UI.

#### Dashboard Changes
- Add login page (JWT auth)
- Update all API calls to include Bearer token
- Update API response parsing for new Pydantic schemas
- Add funding rate display to positions table
- Add regime detection indicator to chart
- Add max exposure / risk-per-trade to settings page
- Show engine state machine status (not just running/stopped)

---

## New Dependencies

```toml
[project]
dependencies = [
    "binance-sdk-derivatives-trading-usds-futures",   # Official Binance SDK
    "pydantic>=2.6",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.29",
    "asyncpg>=0.30",                                   # PostgreSQL async driver
    "sqlalchemy[asyncio]>=2.0",                        # ORM + async
    "alembic>=1.13",                                   # DB migrations
    "python-jose[cryptography]>=3.3",                  # JWT tokens
    "passlib[bcrypt]>=1.7",                            # Password hashing
]
# REMOVED: python-binance, pandas, pandas-ta
```

---

## Verification Plan

### Automated Tests
- Port all 28 existing test files to new module paths
- Add tests for new modules: state_machine, position_sizer, portfolio, auth, trailing
- Target: >80% coverage on core modules
- Run: `pytest tests/ -v --cov=dashrock --cov-report=term-missing`

### Integration Tests
- Full scenario: startup → candle → entry → trailing → exit → cooldown → re-entry
- Crash recovery: kill process mid-trade, restart, verify state restored
- Auth: verify all endpoints reject unauthenticated requests
- PostgreSQL: verify concurrent writes don't deadlock

### Manual Verification
- Run in paper mode for 24 hours, verify equity curve accuracy
- Compare v1 vs v2 paper results on same timeframe/symbol
- Test kill switch and resume with positions open
- Test WebSocket reconnection by killing network briefly

---

## Open Questions

> [!IMPORTANT]
> **Q1**: Do you have PostgreSQL installed locally, or should we use Docker for the dev database?

> [!IMPORTANT]
> **Q2**: For API auth — do you want a simple hardcoded username/password in config, or a proper user management system?

> [!IMPORTANT]
> **Q3**: The official Binance SDK (`binance-sdk-derivatives-trading-usds-futures`) is relatively new. Do you want me to verify it has all the endpoints we need by reading its full documentation first, or should we start building and handle any gaps?

> [!IMPORTANT]
> **Q4**: For the React dashboard — should we rebuild it too (it's also fairly basic), or just update the API calls to match the new backend?
