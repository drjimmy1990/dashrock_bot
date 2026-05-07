"""Dashrock v2 — Application entry point.

Replaces v1's god-function with a structured Application class.
All components are created and wired in initialize(), then run() starts services.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from dashrock.adapters.base import ExecutionAdapter
from dashrock.adapters.simulator import SimulatorAdapter
from dashrock.adapters.binance_live import BinanceLiveAdapter
from dashrock.api.app_factory import create_api
from dashrock.api.auth import configure_auth
from dashrock.api.deps import EngineState
from dashrock.api.ws import ws_manager
from dashrock.config import Config, load_config
from dashrock.core.events import (
    CandleClosed, CandleUpdated, EventBus, EquityUpdate, FillEvent,
    OrderCancelled, OrderPlaced, PositionClosed, PositionOpened,
    SafetyTriggered, TickUpdate,
)
from dashrock.core.state_machine import EngineStateMachine, EngineStatus
from dashrock.core.types import BookTop, Candle, OrderIntent, OrderSide, OrderType, PositionState
from dashrock.execution.manager import ExecutionManager
from dashrock.market.binance_ws import create_binance_ws_factory
from dashrock.market.data_service import MarketDataService
from dashrock.market.symbol_registry import SymbolRegistry
from dashrock.notifications.notifier import Notifier
from dashrock.persistence.database import Database
from dashrock.persistence.repositories import Repository
from dashrock.risk.portfolio import PortfolioRiskManager
from dashrock.risk.safety import SafetyMonitor
from dashrock.strategy.base import Strategy
from dashrock.strategy import registry as strategy_registry
from dashrock.utils.logger import setup_logging
from dashrock.utils.reconciliation import reconcile
from dashrock.utils.spread_guard import check_spread
from dashrock.utils.time_filter import evaluate as evaluate_time_filter

log = logging.getLogger(__name__)


class Application:
    """Main application orchestrator with clean lifecycle."""

    def __init__(self, config_path: Path, port: int = 8000) -> None:
        self.config_path = config_path
        self.port = port
        self.sm = EngineStateMachine()
        self.bus = EventBus()
        self.cfg: Config | None = None
        self.db: Database | None = None
        self.repo: Repository | None = None
        self.adapter: ExecutionAdapter | None = None
        self.manager: ExecutionManager | None = None
        self.md: MarketDataService | None = None
        self.strategy: Strategy | None = None
        self.safety: SafetyMonitor | None = None
        self.portfolio: PortfolioRiskManager | None = None
        self.notifier: Notifier | None = None
        self.registry: SymbolRegistry | None = None
        self._engine_state = EngineState()
        self._tick_counter = 0
        self._candle_update_counter = 0
        self._last_tick_time: dict[str, float] = {}  # per-symbol tick throttle

    async def initialize(self) -> None:
        """Create all components and wire them together."""
        self.cfg = load_config(self.config_path)
        setup_logging(self.cfg.logging)
        log.info("Dashrock v2.0.0 starting — mode=%s", self.cfg.mode)

        # 1. Auth
        configure_auth(
            jwt_secret=os.environ.get("JWT_SECRET", self.cfg.auth.jwt_secret),
            token_expiry_hours=self.cfg.auth.token_expiry_hours,
            admin_username=os.environ.get("ADMIN_USERNAME", self.cfg.auth.admin_username),
            admin_password=os.environ.get("ADMIN_PASSWORD", self.cfg.auth.admin_password),
        )

        # 2. Database
        self.db = Database(self.cfg.database)
        await self.db.connect()
        self.repo = Repository(self.db)

        # 3. Adapter
        self.adapter = self._create_adapter()
        await self.adapter.start()
        self.adapter.set_fill_handler(self._on_fill)

        # 4. Symbol registry
        self.registry = SymbolRegistry()
        if self.cfg.mode == "paper":
            self.registry.load_defaults(self.cfg.watchlist)
        else:
            # Live/testnet: fetch real exchange info for accurate tick/step sizes
            base_url = (
                "https://fapi.binance.com" if self.cfg.mode == "live"
                else "https://testnet.binancefuture.com"
            )
            await self.registry.load_from_binance(base_url)
            log.info("Exchange info loaded for %s mode", self.cfg.mode)

        # 5. Strategy
        self.strategy = strategy_registry.create(
            self.cfg.strategy.name, self.cfg.strategy.params,
        )
        if hasattr(self.strategy, "configure"):
            self.strategy.configure(self.cfg.strategy)  # type: ignore

        # 6. Safety + portfolio
        self.safety = SafetyMonitor(self.cfg.safety)
        self.portfolio = PortfolioRiskManager(self.cfg.portfolio_risk)

        # 7. Execution manager
        self.manager = ExecutionManager(
            adapter=self.adapter,
            config=self.cfg,
            repo=self.repo,
            bus=self.bus,
            registry=self.registry,
        )
        await self.manager.load_persisted_states()

        # 7b. Live/testnet: reconcile exchange state with local DB
        if self.cfg.mode != "paper":
            await self._reconcile_on_startup()

        # 8. Market data — WS streams only for actively traded symbols
        # The full watchlist is handled by the scanner via REST API on demand.
        self.md = MarketDataService(
            bus=self.bus,
            symbols=self.cfg.trade_list,
            timeframes=[self.cfg.timeframe],
            ws_factory=create_binance_ws_factory(self.cfg.timeframe, mode=self.cfg.mode),
            window_size=1000,
        )

        # 8b. Seed chart with historical candles from Binance public API
        await self._seed_historical_candles()

        # 8c. Live/testnet: detect position mode + auto-set leverage/margin
        if self.cfg.mode != "paper" and isinstance(self.adapter, BinanceLiveAdapter):
            # Detect and cache position mode (One-Way vs Hedge)
            try:
                is_hedge = await self.adapter.get_position_mode()
                self.adapter._hedge_mode = is_hedge
                mode_label = "HEDGE" if is_hedge else "ONE-WAY"
                log.info("Binance position mode: %s", mode_label)
            except Exception:
                log.warning("Could not detect position mode, assuming One-Way", exc_info=True)
                self.adapter._hedge_mode = False

            for sym in self.cfg.trade_list:
                try:
                    if self.cfg.live.auto_set_leverage:
                        await self.adapter.set_leverage(sym, self.cfg.sizing.leverage)
                    if self.cfg.live.auto_set_margin_type:
                        await self.adapter.set_margin_type(sym, self.cfg.live.margin_type)
                except Exception:
                    log.warning("Failed to configure %s on exchange", sym, exc_info=True)

        # 9. Notifier
        self.notifier = Notifier(self.cfg.notifications)

        # 10. Wire events
        self._wire_events()

        # 11. Populate shared engine state for API
        self._engine_state.state_machine = self.sm
        self._engine_state.adapter = self.adapter
        self._engine_state.manager = self.manager
        self._engine_state.db = self.db
        self._engine_state.repo = self.repo
        self._engine_state.notifier = self.notifier
        self._engine_state.strategy = self.strategy
        self._engine_state.safety = self.safety
        self._engine_state.config = self.cfg
        self._engine_state.registry = self.registry
        self._engine_state.md = self.md
        self._engine_state.config_path = self.config_path
        self._engine_state.start_time = time.time()

        self.sm.mark_ready("all components initialized")

    async def _seed_historical_candles(self) -> None:
        """Fetch historical candles from Binance public API to seed charts."""
        assert self.cfg is not None and self.md is not None
        import httpx
        base = "https://fapi.binance.com/fapi/v1/klines"
        async with httpx.AsyncClient(timeout=15) as client:
            for sym in self.cfg.trade_list:
                try:
                    r = await client.get(base, params={
                        "symbol": sym.upper(), "interval": self.cfg.timeframe, "limit": 1000,
                    })
                    if r.status_code != 200:
                        log.warning("Failed to seed %s: HTTP %d", sym, r.status_code)
                        continue
                    rows = r.json()
                    # Binance returns the current forming candle as the last entry.
                    # Exclude it — it's not actually closed, and the live WS will
                    # provide it via get_live_candle(), avoiding duplicate timestamps.
                    if rows and len(rows) > 1:
                        rows = rows[:-1]
                    candles = [
                        Candle(
                            symbol=sym.upper(),
                            open_time_ms=int(row[0]), close_time_ms=int(row[6]),
                            open=float(row[1]), high=float(row[2]),
                            low=float(row[3]), close=float(row[4]),
                            volume=float(row[5]), is_closed=True,
                        )
                        for row in rows
                    ]
                    self.md.seed_window(sym.upper(), self.cfg.timeframe, candles)
                except Exception:
                    log.warning("Could not seed candles for %s", sym, exc_info=True)

    def _create_adapter(self) -> ExecutionAdapter:
        assert self.cfg is not None
        if self.cfg.mode == "paper":
            return SimulatorAdapter(self.cfg.simulator)

        # Live and testnet use the same adapter with different URLs/keys
        if self.cfg.mode == "live":
            api_key = os.environ.get("BINANCE_API_KEY", "")
            api_secret = os.environ.get("BINANCE_API_SECRET", "")
            base_url = "https://fapi.binance.com"
            ws_url = "wss://fstream.binance.com"
        else:  # testnet
            api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
            api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
            base_url = "https://testnet.binancefuture.com"
            ws_url = "wss://fstream.binancefuture.com"

        if not api_key or not api_secret:
            raise ValueError(
                f"Missing API keys for {self.cfg.mode} mode. "
                f"Set BINANCE_{'TESTNET_' if self.cfg.mode == 'testnet' else ''}API_KEY "
                f"and BINANCE_{'TESTNET_' if self.cfg.mode == 'testnet' else ''}API_SECRET in .env"
            )

        return BinanceLiveAdapter(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
            ws_url=ws_url,
            cfg=self.cfg,
        )

    async def _reconcile_on_startup(self) -> None:
        """Reconcile exchange state with local DB on startup (live/testnet only).

        Detects and handles:
        1. Orphan positions on exchange (DB says FLAT) → adopt into engine state
        2. Stale positions in DB (exchange is flat) → mark as closed
        3. Missing SL/TP orders for known positions → log warning
        """
        assert self.adapter and self.manager and self.cfg
        if self.cfg.mode == "paper" or not self.cfg.live.startup_reconcile:
            return

        log.info("Starting exchange reconciliation...")

        for sym in self.cfg.trade_list:
            try:
                # Get exchange state
                exchange_pos = await self.adapter.get_position(sym)
                exchange_orders = await self.adapter.get_open_orders(sym)

                # Get local state
                local_state = self.manager.get_state(sym)

                exchange_has_position = exchange_pos.side is not None and exchange_pos.quantity > 0
                local_has_position = local_state.has_position

                if exchange_has_position and not local_has_position:
                    # Case 1: Exchange has position, DB doesn't know about it
                    log.warning(
                        "RECONCILE: %s has ORPHAN position on exchange: "
                        "%s qty=%.8g entry=%.8g — adopting into engine state",
                        sym, exchange_pos.side.value if exchange_pos.side else "?",
                        exchange_pos.quantity, exchange_pos.entry_price,
                    )
                    # Adopt the position into our state
                    from dashrock.core.types import PositionState
                    local_state.position_state = (
                        PositionState.LONG if exchange_pos.side == OrderSide.BUY
                        else PositionState.SHORT
                    )
                    local_state.position_qty = exchange_pos.quantity
                    local_state.entry_price = exchange_pos.entry_price
                    local_state.entry_time_ms = exchange_pos.opened_at_ms
                    local_state.trailing_watermark = exchange_pos.entry_price

                    # Check if SL/TP/TSL orders exist on exchange
                    for order in exchange_orders:
                        if order.order_type == OrderType.TRAILING_STOP_MARKET:
                            local_state.tsl_id = order.order_id
                        elif order.tag in ("sl", "trailing_sl") or order.order_type == OrderType.STOP_MARKET:
                            local_state.sl_id = order.order_id
                            local_state.sl_price = order.stop_price
                        elif order.tag == "tp" or order.order_type == OrderType.TAKE_PROFIT_MARKET:
                            local_state.tp_id = order.order_id
                            local_state.tp_price = order.stop_price

                    if not local_state.sl_id:
                        log.critical(
                            "RECONCILE: %s has position but NO SL ORDER — DANGER!",
                            sym,
                        )

                    await self.manager._persist_state(sym)

                elif local_has_position and not exchange_has_position:
                    # Case 2: DB thinks we have position, but exchange is flat
                    log.warning(
                        "RECONCILE: %s DB has position (%s qty=%.8g) but exchange is FLAT "
                        "— position was likely closed while engine was down",
                        sym, local_state.position_state.value,
                        local_state.position_qty,
                    )
                    # Record as a missed trade with unknown exit price
                    from dashrock.core.types import TradeRecord
                    trade = TradeRecord(
                        symbol=sym,
                        side=local_state.position_state.value,
                        entry_price=local_state.entry_price,
                        exit_price=0,  # unknown
                        quantity=local_state.position_qty,
                        realized_pnl=0,  # unknown
                        fees=local_state.entry_fee,
                        entry_time_ms=local_state.entry_time_ms,
                        exit_time_ms=int(time.time() * 1000),
                        exit_reason="missed_fill",
                        funding_cost=local_state.accumulated_funding,
                    )
                    await self.repo.insert_trade(trade)
                    await self.manager.clear_state(sym)
                    log.info("RECONCILE: %s state cleared, trade recorded as missed_fill", sym)

                elif exchange_has_position and local_has_position:
                    # Case 3: Both agree — verify SL/TP still exist
                    sl_exists = any(
                        o.order_id == local_state.sl_id for o in exchange_orders
                    ) if local_state.sl_id else False
                    if not sl_exists and local_state.sl_id:
                        log.warning(
                            "RECONCILE: %s SL order %s is MISSING from exchange!",
                            sym, local_state.sl_id,
                        )
                        local_state.sl_id = None
                        local_state.sl_price = None

                    # In binance_native mode: ensure emergency SL exists on exchange
                    if (self.cfg.trailing.enabled
                            and self.cfg.trailing.mode == "binance_native"
                            and local_state.has_position
                            and not sl_exists):
                        log.warning(
                            "RECONCILE: %s has position but NO emergency SL on exchange — placing one now",
                            sym,
                        )
                        sl_side = (OrderSide.SELL
                                   if local_state.position_state == PositionState.LONG
                                   else OrderSide.BUY)
                        sl_price = self.manager._calculate_sl_price(OrderIntent(
                            symbol=sym, side=local_state.position_side,
                            order_type=OrderType.STOP_MARKET,
                            stop_price=local_state.entry_price, quantity=0,
                        ))
                        sl_price = self.manager._registry.round_price(sym, sl_price)
                        sl_order = await self.manager._safe_place_order(OrderIntent(
                            symbol=sym, side=sl_side,
                            order_type=OrderType.STOP_MARKET,
                            stop_price=sl_price,
                            quantity=local_state.position_qty,
                            reduce_only=True,
                            tag=f"sl_emergency_{int(time.time()*1000)}",
                        ))
                        if sl_order:
                            local_state.sl_id = sl_order.order_id
                            local_state.sl_price = sl_price
                            log.info(
                                "RECONCILE: Emergency SL placed for %s @ %.8g",
                                sym, sl_price,
                            )
                        else:
                            log.error("RECONCILE: Failed to place emergency SL for %s!", sym)

                    # Check if TSL is also missing and re-place it
                    tsl_exists = any(
                        o.order_id == local_state.tsl_id for o in exchange_orders
                    ) if local_state.tsl_id else False
                    if (self.cfg.trailing.enabled
                            and self.cfg.trailing.mode == "binance_native"
                            and local_state.has_position
                            and not tsl_exists):
                        log.warning(
                            "RECONCILE: %s has position but NO TSL on exchange — placing one now",
                            sym,
                        )
                        from dashrock.core.events import NativeTrailingPlaced
                        tsl_side = (OrderSide.SELL
                                    if local_state.position_state == PositionState.LONG
                                    else OrderSide.BUY)
                        callback_rate = self.cfg.trailing.stop_pips
                        activate_price = None
                        if self.cfg.trailing.activation_pips > 0:
                            if local_state.position_state == PositionState.LONG:
                                activate_price = local_state.entry_price * (1 + self.cfg.trailing.activation_pips / 100.0)
                            else:
                                activate_price = local_state.entry_price * (1 - self.cfg.trailing.activation_pips / 100.0)
                            activate_price = self.manager._registry.round_price(sym, activate_price)

                        tsl_order = await self.manager._safe_place_order(OrderIntent(
                            symbol=sym, side=tsl_side,
                            order_type=OrderType.TRAILING_STOP_MARKET,
                            stop_price=None,
                            quantity=local_state.position_qty,
                            reduce_only=True,
                            callback_rate=callback_rate,
                            activate_price=activate_price,
                            tag=f"native_tsl_{int(time.time()*1000)}",
                        ))
                        if tsl_order:
                            local_state.tsl_id = tsl_order.order_id
                            log.info("RECONCILE: TSL re-placed for %s", sym)

                    # Cancel orphan ENTRY orders — these should NOT exist when position is open
                    known_ids = {local_state.sl_id, local_state.tp_id, local_state.tsl_id}
                    known_ids.discard(None)
                    for order in exchange_orders:
                        if order.order_id not in known_ids:
                            tag = order.tag or ""
                            # This is an orphan — cancel it
                            try:
                                await self.adapter.cancel_order(sym, order.order_id)
                                log.warning(
                                    "RECONCILE: Cancelled orphan order %s for %s (%s %s stop=%s tag=%s)",
                                    order.order_id, sym,
                                    order.side.value if order.side else "?",
                                    order.order_type.value if order.order_type else "?",
                                    order.stop_price, tag,
                                )
                            except Exception:
                                log.warning(
                                    "RECONCILE: Failed to cancel orphan order %s for %s",
                                    order.order_id, sym, exc_info=True,
                                )

                    # Clear stale entry IDs since position is already open
                    local_state.entry_buy_id = None
                    local_state.entry_buy_stop_price = None
                    local_state.entry_sell_id = None
                    local_state.entry_sell_stop_price = None
                    await self.manager._persist_state(sym)

                    log.info(
                        "RECONCILE: %s state consistent — %s qty=%.8g sl=%s tsl=%s",
                        sym, local_state.position_state.value, local_state.position_qty,
                        local_state.sl_id or "NONE", local_state.tsl_id or "NONE",
                    )

                else:
                    # Case 4: Both flat — BUT check for orphan orders on exchange
                    if exchange_orders:
                        log.warning(
                            "RECONCILE: %s — both FLAT but %d orphan orders on exchange! Cancelling all...",
                            sym, len(exchange_orders),
                        )
                        for order in exchange_orders:
                            try:
                                await self.adapter.cancel_order(sym, order.order_id)
                                log.info(
                                    "RECONCILE: Cancelled orphan %s %s order %s (stop=%s tag=%s)",
                                    sym, order.side.value if order.side else "?",
                                    order.order_id,
                                    order.stop_price, order.tag or "?",
                                )
                            except Exception:
                                log.warning(
                                    "RECONCILE: Failed to cancel orphan order %s for %s",
                                    order.order_id, sym, exc_info=True,
                                )
                        # Also clear any stale IDs in engine state
                        local_state.entry_buy_id = None
                        local_state.entry_buy_stop_price = None
                        local_state.entry_sell_id = None
                        local_state.entry_sell_stop_price = None
                        local_state.sl_id = None
                        local_state.sl_price = None
                        local_state.tp_id = None
                        local_state.tp_price = None
                        local_state.tsl_id = None
                        await self.manager._persist_state(sym)
                    else:
                        log.debug("RECONCILE: %s — both flat, OK", sym)

            except Exception:
                log.error("RECONCILE: Failed for %s", sym, exc_info=True)

    async def _compute_initial_signals(self) -> None:
        """Run strategy on seeded candles to place orders immediately at startup."""
        if not self.sm.is_trading_allowed:
            log.info("Engine is paused. Skipping initial signals.")
            return

        assert self.cfg and self.strategy and self.manager and self.adapter and self.md

        equity = await self.adapter.get_equity_usd()
        placed = 0
        for symbol in self.cfg.trade_list:
            try:
                window = self.md.get_window(symbol)
                if not window:
                    log.debug("No seeded candles for %s, skipping initial signal", symbol)
                    continue
                current_price = self.md.get_current_price(symbol)
                state = self.manager.get_state(symbol)
                desired = self.strategy.compute(
                    symbol, {self.cfg.timeframe: window},
                    state.position_state, current_price,
                )
                await self.manager.apply_desired(desired, equity=equity)
                placed += 1
                if desired.buy_stop:
                    log.info("Initial BUY STOP %s @ %.8g", symbol, desired.buy_stop.stop_price or 0)
                if desired.sell_stop:
                    log.info("Initial SELL STOP %s @ %.8g", symbol, desired.sell_stop.stop_price or 0)
            except Exception:
                log.warning("Failed initial signal for %s", symbol, exc_info=True)
        log.info("Initial signals computed for %d symbols", placed)

    def _wire_events(self) -> None:
        """Connect EventBus to handlers and WebSocket bridge."""
        # Strategy: on candle close → compute signals → apply
        self.bus.subscribe(CandleClosed, self._on_candle_closed)
        # Trailing: on tick → update trailing stop
        self.bus.subscribe(TickUpdate, self._on_tick_update)
        # WS bridge: forward key events to dashboard
        self.bus.subscribe(CandleClosed, self._ws_bridge_candle)
        self.bus.subscribe(CandleUpdated, self._ws_bridge_live_candle)
        self.bus.subscribe(TickUpdate, self._ws_bridge_tick)
        self.bus.subscribe(FillEvent, self._ws_bridge_fill)
        self.bus.subscribe(OrderPlaced, self._ws_bridge_order_placed)
        self.bus.subscribe(OrderCancelled, self._ws_bridge_order_cancelled)
        self.bus.subscribe(PositionOpened, self._ws_bridge_position_opened)
        self.bus.subscribe(PositionClosed, self._ws_bridge_position_closed)
        self.bus.subscribe(SafetyTriggered, self._ws_bridge_safety)
        self.bus.subscribe(EquityUpdate, self._ws_bridge_equity)
        
        from dashrock.core.events import TrailingMoved, NativeTrailingPlaced
        self.bus.subscribe(TrailingMoved, self._ws_bridge_trailing_moved)
        self.bus.subscribe(NativeTrailingPlaced, self._ws_bridge_native_trailing)

    # ─── Main Loop ───────────────────────────────────

    async def run(self) -> None:
        await self.initialize()
        
        # Always boot into running state so overnight restarts don't stall trading.
        # Safety circuit breakers will pause if limits are breached.
        if self.manager:
            for sym in self.cfg.trade_list:
                state = self.manager.get_state(sym)
                has_orders = any([state.entry_buy_id, state.entry_sell_id, state.sl_id, state.tp_id])
                if state.has_position or has_orders:
                    log.info("Boot: found active state for %s — resuming.", sym)
                    break

        self.sm.start("auto-start on boot")

        # Start API server
        api = create_api(self._engine_state, auth_enabled=self.cfg.auth.enabled)  # type: ignore
        api_config = uvicorn.Config(api, host="0.0.0.0", port=self.port, log_level="warning")
        api_server = uvicorn.Server(api_config)

        # Compute initial signals from seeded candles BEFORE starting live data.
        # This ensures both buy/sell stops exist before any ticks can trigger fills.
        await self._compute_initial_signals()

        # Start market data (WebSocket streams)
        await self.md.start()  # type: ignore

        # Register signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                pass  # Windows doesn't support add_signal_handler

        log.info("Engine RUNNING. API at http://0.0.0.0:%d", self.port)
        try:
            await api_server.serve()
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        log.info("Shutting down...")
        self.sm.stop("shutdown requested")
        # Persist all execution states
        if self.manager and self.repo:
            for symbol in (self.cfg.trade_list if self.cfg else []):
                await self.manager._persist_state(symbol)
        if self.md:
            await self.md.stop()
        if self.adapter:
            await self.adapter.stop()
        if self.notifier:
            await self.notifier.close()
        if self.db:
            await self.db.close()
        log.info("Shutdown complete.")

    # ─── Event Handlers ──────────────────────────────

    async def _on_candle_closed(self, event: CandleClosed) -> None:
        candle = event.candle
        symbol = candle.symbol

        if not self.sm.is_trading_allowed:
            log.debug("Candle closed %s — trading not allowed (state=%s)", symbol, self.sm.status.value)
            return
        assert self.cfg and self.strategy and self.manager and self.adapter and self.md

        if symbol not in self.cfg.trade_list:
            return

        log.debug("CANDLE CLOSED: %s O=%.4f H=%.4f L=%.4f C=%.4f", symbol, candle.open, candle.high, candle.low, candle.close)

        # Safety check — wrap DB calls so they can't kill the handler
        try:
            equity = await self.adapter.get_equity_usd()
        except Exception:
            log.warning("Failed to fetch equity for %s — skipping safety check this candle", symbol, exc_info=True)
            equity = None  # None = skip drawdown check, not 0

        try:
            daily_pnl = await self.repo.get_todays_realized_pnl() if self.repo else 0
            hw = await self.repo.get_equity_high_water() if self.repo else (equity or 0)
            losses = await self.repo.get_consecutive_losses() if self.repo else 0
        except Exception:
            log.warning("Failed to fetch safety metrics — skipping safety check", exc_info=True)
            daily_pnl, hw, losses = 0, equity or 0, 0

        # Only run drawdown check if we have a valid equity reading
        safety = self.safety.check(
            daily_pnl=daily_pnl, starting_equity=self.cfg.simulator.starting_equity_usd,
            current_equity=equity if equity is not None else hw,  # fallback to hw = 0% drawdown
            high_water_equity=hw,
            consecutive_losses=losses,
            skip_drawdown=equity is None,  # skip drawdown if equity fetch failed
        ) if self.safety else None

        if safety and not safety.trading_allowed:
            log.warning("Safety blocked: %s", safety.reason)
            self.sm.pause(f"safety: {safety.reason}")  # Auto-pause engine
            await self.bus.publish(SafetyTriggered(
                reason=safety.reason, timestamp_ms=int(time.time() * 1000),
            ))
            if self.notifier:
                await self.notifier.send("safety_triggered", f"⚠️ Safety: {safety.reason}")
            return

        # Time filter
        blackout = evaluate_time_filter(self.cfg.time_filter, datetime.now(timezone.utc))

        # Compute strategy
        window = self.md.get_window(symbol)
        current_price = self.md.get_current_price(symbol)
        state = self.manager.get_state(symbol)
        desired = self.strategy.compute(
            symbol, {self.cfg.timeframe: window},
            state.position_state, current_price,
        )

        # Portfolio risk check
        if desired.buy_stop or desired.sell_stop:
            entry_price = (desired.buy_stop or desired.sell_stop).stop_price or 0  # type: ignore
            notional = equity * (self.cfg.sizing.risk_per_trade_pct / 100) * self.cfg.sizing.leverage
            if self.portfolio:
                check = self.portfolio.check_new_entry(
                    symbol, notional, equity, self.manager._states, self.cfg.sizing.leverage,
                )
                if not check.allowed:
                    log.info("Portfolio blocked %s: %s", symbol, check.reason)
                    return

        await self.manager.apply_desired(desired, equity=equity, blackout=blackout)

        # Equity snapshot
        try:
            if self.repo:
                await self.repo.insert_equity_snapshot(equity)
        except Exception:
            log.warning("Failed to persist equity snapshot", exc_info=True)
        await self.bus.publish(EquityUpdate(equity_usd=equity, timestamp_ms=int(time.time() * 1000)))

    async def _on_tick_update(self, event: TickUpdate) -> None:
        if not self.sm.is_trading_allowed or not self.manager:
            return
        book = event.book

        # Throttle: max 2 tick updates per second per symbol to avoid
        # overwhelming the DB pool and event loop with 500+ ticks/sec
        now = time.monotonic()
        last = self._last_tick_time.get(book.symbol, 0)
        if now - last < 0.5:
            return
        self._last_tick_time[book.symbol] = now

        # Feed simulator
        if isinstance(self.adapter, SimulatorAdapter):
            await self.adapter.on_book(book)
        # Trailing stop
        price = (book.bid + book.ask) / 2
        await self.manager.on_tick(book.symbol, price)

    async def _on_fill(self, fill) -> None:
        """Fill callback from adapter — routes to execution manager."""
        # Capture position state BEFORE on_fill mutates it (fixes notification race)
        was_flat = True
        if self.manager:
            was_flat = not self.manager.get_state(fill.symbol).has_position
            await self.manager.on_fill(fill)

            # Notify strategy of fills so it can clear fixed levels
            # (critical for pending_refresh_mode=fixed — without this,
            # _fixed_levels are never cleared and the strategy reuses stale HH/LL)
            if self.strategy:
                self.strategy.on_fill(fill.symbol, fill)

        if self.notifier:
            event_type = "trade_opened" if was_flat else "trade_closed"
            await self.notifier.send(
                event_type,
                f"{'📈' if fill.side.value == 'BUY' else '📉'} {fill.symbol} {fill.side.value} @ {fill.price:.8g} qty={fill.quantity:.8g}",
            )

    # ─── WS Bridge ───────────────────────────────────

    async def _ws_bridge_candle(self, e: CandleClosed) -> None:
        await ws_manager.broadcast_json({"type": "candle", "data": {
            "symbol": e.candle.symbol,
            "time": e.candle.open_time_ms // 1000,
            "open": e.candle.open, "high": e.candle.high,
            "low": e.candle.low, "close": e.candle.close,
        }})

    async def _ws_bridge_live_candle(self, e: CandleUpdated) -> None:
        """Send forming candle to dashboard for live chart updates."""
        self._candle_update_counter += 1
        if self._candle_update_counter % 3 == 0:  # throttle: every 3rd update
            await ws_manager.broadcast_json({"type": "candle", "data": {
                "symbol": e.candle.symbol,
                "time": e.candle.open_time_ms // 1000,
                "open": e.candle.open, "high": e.candle.high,
                "low": e.candle.low, "close": e.candle.close,
            }})

    async def _ws_bridge_tick(self, e: TickUpdate) -> None:
        self._tick_counter += 1
        if self._tick_counter % 5 == 0:  # throttle to every 5th tick
            await ws_manager.broadcast_json({"type": "tick", "data": {
                "symbol": e.book.symbol, "bid": e.book.bid, "ask": e.book.ask,
            }})

    async def _ws_bridge_fill(self, e: FillEvent) -> None:
        await ws_manager.broadcast_json({"type": "fill", "data": {
            "symbol": e.fill.symbol, "side": e.fill.side.value,
            "price": e.fill.price, "qty": e.fill.quantity,
            "timestamp_ms": e.fill.timestamp_ms,
        }})

    async def _ws_bridge_order_placed(self, e: OrderPlaced) -> None:
        await ws_manager.broadcast_json({"type": "order_placed", "data": {
            "symbol": e.order.symbol, "side": e.order.side.value,
            "type": e.order.order_type.value, "stop": e.order.stop_price,
            "qty": e.order.quantity,
            "timestamp_ms": int(time.time() * 1000),
        }})

    async def _ws_bridge_order_cancelled(self, e: OrderCancelled) -> None:
        await ws_manager.broadcast_json({"type": "order_cancelled", "data": {
            "symbol": e.symbol, "order_id": e.order_id,
            "timestamp_ms": int(time.time() * 1000),
        }})

    async def _ws_bridge_trailing_moved(self, e) -> None:
        await ws_manager.broadcast_json({"type": "trailing_moved", "data": {
            "symbol": e.symbol, "new_sl": e.new_sl,
            "timestamp_ms": int(time.time() * 1000),
        }})

    async def _ws_bridge_native_trailing(self, e) -> None:
        await ws_manager.broadcast_json({"type": "native_trailing", "data": {
            "symbol": e.symbol,
            "callback_rate": e.callback_rate,
            "activate_price": e.activate_price,
            "order_id": e.order_id,
            "timestamp_ms": int(time.time() * 1000),
        }})

    async def _ws_bridge_position_opened(self, e: PositionOpened) -> None:
        await ws_manager.broadcast_json({"type": "position_opened", "data": {
            "symbol": e.symbol, "side": e.side, "entry": e.entry_price, "qty": e.quantity,
            "timestamp_ms": e.timestamp_ms,
        }})

    async def _ws_bridge_position_closed(self, e: PositionClosed) -> None:
        await ws_manager.broadcast_json({"type": "position_closed", "data": {
            "symbol": e.symbol, "pnl": e.realized_pnl, "reason": e.exit_reason,
            "timestamp_ms": e.timestamp_ms,
        }})

    async def _ws_bridge_safety(self, e: SafetyTriggered) -> None:
        await ws_manager.broadcast_json({"type": "safety", "data": {"reason": e.reason}})

    async def _ws_bridge_equity(self, e: EquityUpdate) -> None:
        await ws_manager.broadcast_json({"type": "equity", "data": {"equity": e.equity_usd}})


def cli() -> None:
    parser = argparse.ArgumentParser(prog="dashrock")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    load_dotenv()
    app = Application(config_path=args.config, port=args.port)
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        log.info("Interrupted")
