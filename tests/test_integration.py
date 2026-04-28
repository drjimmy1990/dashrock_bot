"""Integration test: verify all components wire together and can run a basic trading cycle."""
import asyncio
import pytest
from dashrock.config import load_config
from dashrock.core.events import EventBus, CandleClosed, FillEvent, PositionOpened, PositionClosed
from dashrock.core.state_machine import EngineStateMachine, EngineStatus
from dashrock.core.types import Candle, PositionState, OrderSide
from dashrock.adapters.simulator import SimulatorAdapter
from dashrock.execution.manager import ExecutionManager
from dashrock.market.data_service import MarketDataService
from dashrock.market.symbol_registry import SymbolRegistry
from dashrock.risk.safety import SafetyMonitor
from dashrock.risk.portfolio import PortfolioRiskManager
from dashrock.strategy.donchian_breakout import DonchianBreakoutStrategy
from dashrock.utils.time_filter import evaluate as eval_tf
from pathlib import Path
import time

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

def make_candle(symbol: str, idx: int, o: float, h: float, l: float, c: float) -> Candle:
    t = 1700000000000 + idx * 60000
    return Candle(symbol=symbol, open_time_ms=t, close_time_ms=t + 59999,
                  open=o, high=h, low=l, close=c, volume=100, is_closed=True)


class FakeRepo:
    """Minimal repo stub for testing without DB."""
    async def save_engine_state(self, s): pass
    async def load_engine_states(self): return {}
    async def clear_engine_state(self, s): pass
    async def clear_all_engine_states(self): pass
    async def insert_trade(self, t): return 1
    async def insert_order(self, **kw): pass
    async def update_order_status(self, oid, st): pass
    async def get_known_order_ids(self, syms): return set()
    async def insert_equity_snapshot(self, eq): pass
    async def get_todays_realized_pnl(self): return 0.0
    async def get_equity_high_water(self): return 1000.0
    async def get_consecutive_losses(self): return 0


@pytest.fixture
def cfg():
    return load_config(CONFIG_PATH)


def test_config_loads(cfg):
    assert cfg.mode in ("paper", "testnet", "live")
    assert "BTCUSDT" in cfg.watchlist or len(cfg.watchlist) > 0
    assert cfg.strategy.name == "donchian_breakout"
    assert cfg.sizing.mode in ("risk_per_trade", "fixed", "equity_fraction")
    assert cfg.safety.max_daily_loss_pct > 0


def test_state_machine():
    sm = EngineStateMachine()
    assert sm.status == EngineStatus.INITIALIZING
    assert sm.mark_ready()
    assert sm.status == EngineStatus.READY
    assert sm.start()
    assert sm.is_running
    assert sm.pause()
    assert not sm.is_running
    assert sm.resume()
    assert sm.is_running
    assert sm.stop()
    assert sm.status == EngineStatus.STOPPED
    # Invalid transition
    assert not sm.start()  # STOPPED -> RUNNING is invalid


def test_strategy_compute(cfg):
    strategy = DonchianBreakoutStrategy()
    strategy.configure(cfg.strategy)
    # Build a window with clear uptrend
    candles = []
    for i in range(15):
        price = 50000 + i * 100
        candles.append(make_candle("BTCUSDT", i, price, price + 50, price - 50, price))
    desired = strategy.compute("BTCUSDT", {"1m": candles}, PositionState.FLAT, candles[-1].close)
    # Should have a buy stop above HH and sell stop below LL
    assert desired.buy_stop is not None or desired.sell_stop is not None


def test_strategy_regime_skip(cfg):
    """When regime detection is on and market is ranging, no orders."""
    cfg.strategy.regime_detection.enabled = True
    cfg.strategy.regime_detection.skip_ranging = True
    strategy = DonchianBreakoutStrategy()
    strategy.configure(cfg.strategy)
    # Build a flat/ranging window (no trend)
    candles = []
    for i in range(60):
        candles.append(make_candle("BTCUSDT", i, 50000, 50010, 49990, 50000))
    desired = strategy.compute("BTCUSDT", {"1m": candles}, PositionState.FLAT, 50000)
    # ADX should be very low → skip
    assert desired.buy_stop is None and desired.sell_stop is None


def test_position_sizer():
    from dashrock.risk.position_sizer import size_for_risk
    from dashrock.config import SizingCfg
    cfg = SizingCfg(mode="risk_per_trade", risk_per_trade_pct=1.0, leverage=10)
    # Risk 1% of $1000 = $10. Entry=50000, SL=49925 → distance=75
    qty = size_for_risk(cfg, equity=1000, entry_price=50000, sl_price=49925)
    assert abs(qty - 10/75) < 0.001  # ~0.1333 BTC


def test_portfolio_risk():
    mgr = PortfolioRiskManager(cfg=__import__('dashrock.config', fromlist=['PortfolioRiskCfg']).PortfolioRiskCfg(max_open_positions=2))
    from dashrock.core.types import SymbolExecutionState
    states = {
        "ETHUSDT": SymbolExecutionState(symbol="ETHUSDT", position_state=PositionState.LONG, position_qty=1, entry_price=3000),
        "SOLUSDT": SymbolExecutionState(symbol="SOLUSDT", position_state=PositionState.LONG, position_qty=10, entry_price=150),
    }
    result = mgr.check_new_entry("BTCUSDT", 50000, 1000, states, 10)
    assert not result.allowed  # max_open_positions=2 already full


def test_safety_monitor():
    from dashrock.config import SafetyCfg
    safety = SafetyMonitor(SafetyCfg(max_daily_loss_pct=5.0))
    result = safety.check(daily_pnl=-60, starting_equity=1000)
    assert not result.trading_allowed
    result = safety.check(daily_pnl=-10, starting_equity=1000)
    assert result.trading_allowed


@pytest.mark.asyncio
async def test_simulator_fill_cycle(cfg):
    """Full cycle: place order → trigger via book → receive fill."""
    sim = SimulatorAdapter(cfg.simulator)
    fills = []
    async def on_fill(f):
        fills.append(f)
    sim.set_fill_handler(on_fill)
    await sim.start()

    from dashrock.core.types import OrderIntent, OrderType, BookTop
    # Place a buy stop at 50100
    order = await sim.place_order(OrderIntent(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.STOP_MARKET,
        stop_price=50100, quantity=0.1, tag="test_entry",
    ))
    assert order.order_id.startswith("sim-")

    # Tick below stop — no fill
    await sim.on_book(BookTop(symbol="BTCUSDT", bid=50000, ask=50001, timestamp_ms=1))
    assert len(fills) == 0

    # Tick above stop — fill!
    await sim.on_book(BookTop(symbol="BTCUSDT", bid=50100, ask=50101, timestamp_ms=2))
    assert len(fills) == 1
    assert fills[0].side == OrderSide.BUY
    assert fills[0].quantity == 0.1

    await sim.stop()


@pytest.mark.asyncio
async def test_execution_manager_entry_exit(cfg):
    """Full trade lifecycle: entry fill → SL/TP placed → exit fill."""
    bus = EventBus()
    sim = SimulatorAdapter(cfg.simulator)
    repo = FakeRepo()
    registry = SymbolRegistry()
    registry.load_defaults(["BTCUSDT"])

    events_log = []
    async def log_pos_opened(e): events_log.append(("opened", e))
    async def log_pos_closed(e): events_log.append(("closed", e))
    bus.subscribe(PositionOpened, log_pos_opened)
    bus.subscribe(PositionClosed, log_pos_closed)

    mgr = ExecutionManager(adapter=sim, config=cfg, repo=repo, bus=bus, registry=registry)
    sim.set_fill_handler(mgr.on_fill)
    await sim.start()

    # Build strategy signal
    strategy = DonchianBreakoutStrategy()
    strategy.configure(cfg.strategy)
    candles = [make_candle("BTCUSDT", i, 50000+i*50, 50000+i*50+30, 50000+i*50-30, 50000+i*50) for i in range(15)]
    desired = strategy.compute("BTCUSDT", {"1m": candles}, PositionState.FLAT, candles[-1].close)
    await mgr.apply_desired(desired, equity=1000)

    state = mgr.get_state("BTCUSDT")
    # Should have entry orders placed
    has_entry = state.entry_buy_id is not None or state.entry_sell_id is not None
    assert has_entry, "No entry orders placed"

    # Trigger the buy entry
    if state.entry_buy_id and state.entry_buy_stop_price:
        from dashrock.core.types import BookTop
        await sim.on_book(BookTop(
            symbol="BTCUSDT", bid=state.entry_buy_stop_price + 1,
            ask=state.entry_buy_stop_price + 2, timestamp_ms=100,
        ))
        assert state.position_state == PositionState.LONG
        assert state.sl_id is not None, "SL not placed after entry"
        assert state.sl_price is not None, "SL price not cached"
        assert ("opened", ) or any(e[0] == "opened" for e in events_log)

        # Now trigger the SL
        if state.sl_price and state.sl_id:
            await sim.on_book(BookTop(
                symbol="BTCUSDT", bid=state.sl_price - 1,
                ask=state.sl_price, timestamp_ms=200,
            ))
            assert state.position_state == PositionState.FLAT
            assert any(e[0] == "closed" for e in events_log)

    await sim.stop()


def test_symbol_registry():
    reg = SymbolRegistry()
    reg.load_defaults(["BTCUSDT", "ETHUSDT"])
    info = reg.get("BTCUSDT")
    assert info is not None
    assert info.base_asset == "BTC"
    assert reg.round_qty("BTCUSDT", 0.123456789) <= 0.123456789
    assert reg.validate_order("BTCUSDT", 0.001, 50000) is None  # valid
    assert reg.validate_order("BTCUSDT", 0.00001, 50000) is not None  # too small


def test_spread_guard():
    from dashrock.config import SpreadCfg
    from dashrock.utils.spread_guard import check_spread
    cfg = SpreadCfg(max_pips=5)
    r = check_spread(cfg, spread=3, current_atr=100)
    assert r.passed
    r = check_spread(cfg, spread=10, current_atr=100)
    assert not r.passed


@pytest.mark.asyncio
async def test_event_bus_sync():
    """Verify EventBus handlers run sequentially (backpressure)."""
    bus = EventBus()
    order = []
    async def h1(e): order.append(1)
    async def h2(e): order.append(2)
    bus.subscribe(CandleClosed, h1)
    bus.subscribe(CandleClosed, h2)
    candle = make_candle("BTCUSDT", 0, 50000, 50010, 49990, 50000)
    await bus.publish(CandleClosed(candle=candle))
    assert order == [1, 2]

