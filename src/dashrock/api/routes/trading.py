"""API routes — all REST endpoints organized into logical groups."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any


class _Cache:
    """Simple TTL cache for a single value."""
    def __init__(self, ttl_sec: float) -> None:
        self._ttl = ttl_sec
        self._value: Any = None
        self._ts: float = 0.0

    def get(self) -> tuple[bool, Any]:
        if time.monotonic() - self._ts < self._ttl:
            return True, self._value
        return False, None

    def set(self, value: Any) -> Any:
        self._value = value
        self._ts = time.monotonic()
        return value

from fastapi import APIRouter, Depends, HTTPException

from dashrock.api.auth import authenticate, require_auth
from dashrock.api.deps import EngineState
from dashrock.api.schemas import (
    CloseAllResponse, EquitySnapshotResponse, HealthResponse, LoginRequest,
    MessageResponse, OrderResponse, PnlResponse, PositionModeRequest,
    PositionResponse, ScannerResponse, StatusResponse, TokenResponse,
    TradeResponse,
)
from dashrock.core.types import OrderIntent, OrderSide, OrderType

log = logging.getLogger(__name__)


def create_routes(state: EngineState, auth_enabled: bool = True) -> APIRouter:
    """Create all API routes wired to the engine state."""
    router = APIRouter(prefix="/api")
    auth_dep = [Depends(require_auth)] if auth_enabled else []
    _config_lock = asyncio.Lock()

    # TTL caches — avoids hammering Binance on every dashboard refresh
    _equity_cache = _Cache(ttl_sec=15)
    _positions_cache = _Cache(ttl_sec=5)
    _orders_cache = _Cache(ttl_sec=15)

    def _require_ready() -> None:
        if state.adapter is None or state.config is None:
            raise HTTPException(status_code=503, detail="Engine not ready")

    # ─── Auth ────────────────────────────────────────

    @router.post("/auth/login", response_model=TokenResponse)
    async def login(req: LoginRequest) -> TokenResponse:
        token = authenticate(req.username, req.password)
        if not token:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return TokenResponse(access_token=token)

    # ─── Health & Status ─────────────────────────────

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        sm = state.state_machine
        return HealthResponse(
            status="healthy" if sm and sm.is_running else "degraded",
            engine_state=sm.status.value if sm else "unknown",
            db_connected=await state.db.is_connected() if state.db else False,
            ws_connected=state.md.is_connected() if state.md else False,
            uptime_seconds=time.time() - state.start_time if state.start_time else 0,
        )

    @router.get("/status", response_model=StatusResponse, dependencies=auth_dep)
    async def get_status() -> StatusResponse:
        sm = state.state_machine
        return StatusResponse(
            engine_state=sm.status.value if sm else "unknown",
            mode=state.config.mode if state.config else None,
            is_running=sm.is_running if sm else False,
            restart_required=False,
        )

    # ─── Config ──────────────────────────────────────

    @router.get("/config", dependencies=auth_dep)
    async def get_config() -> dict[str, Any]:
        if state.config is None:
            raise HTTPException(status_code=503, detail="Config not loaded")
        return state.config.model_dump()

    @router.put("/config", dependencies=auth_dep)
    async def put_config(updates: dict[str, Any]) -> dict[str, Any]:
        async with _config_lock:
            _require_ready()
            if state.config is None:
                raise HTTPException(status_code=503, detail="Config not loaded")

            # Snapshot the old trade list for change detection
            old_trade_list = list(state.config.trade_list)

            # Update the in-memory config from the incoming dict
            try:
                current = state.config.model_dump()
                for key, value in updates.items():
                    if key in current and isinstance(value, dict) and isinstance(current.get(key), dict):
                        current[key].update(value)
                    else:
                        current[key] = value

                from dashrock.config import Config
                new_cfg = Config(**current)
                state.config = new_cfg

                # Reconfigure strategy with new params
                if state.strategy and hasattr(state.strategy, "configure"):
                    state.strategy.configure(new_cfg.strategy)

                # Reconfigure safety monitor
                if state.safety:
                    state.safety.cfg = new_cfg.safety

                # Reconfigure execution manager's config reference
                if state.manager:
                    state.manager._cfg = new_cfg

                log.info("Config hot-reloaded via API")
            except Exception as e:
                log.exception("Failed to apply config update")
                raise HTTPException(status_code=400, detail=f"Invalid config: {e}")

            # ── Handle trade_list changes ──────────────────────
            new_trade_list = list(new_cfg.trade_list)
            if set(old_trade_list) != set(new_trade_list) and state.md:
                added_symbols = set(new_trade_list) - set(old_trade_list)
                removed_symbols = set(old_trade_list) - set(new_trade_list)

                log.info(
                    "Trade list changed: added=%s removed=%s",
                    list(added_symbols) or "none", list(removed_symbols) or "none",
                )

                # 1. Update symbol registry to include new symbols
                if state.registry and added_symbols:
                    state.registry.load_defaults(new_trade_list)

                # 2. Cancel orders and clear state for removed symbols
                if state.manager and state.adapter:
                    for sym in removed_symbols:
                        try:
                            await state.manager.clear_state(sym)
                            await state.adapter.cancel_all_orders(sym)
                        except Exception:
                            log.warning("Failed to clean up removed symbol %s", sym)

                # 3. Seed historical candles for new symbols
                if added_symbols:
                    import httpx
                    from dashrock.core.types import Candle
                    base_url = "https://fapi.binance.com/fapi/v1/klines"
                    async with httpx.AsyncClient(timeout=15) as client:
                        for sym in added_symbols:
                            try:
                                r = await client.get(base_url, params={
                                    "symbol": sym.upper(),
                                    "interval": new_cfg.timeframe,
                                    "limit": 200,
                                })
                                if r.status_code != 200:
                                    log.warning("Failed to seed %s: HTTP %d", sym, r.status_code)
                                    continue
                                rows = r.json()
                                if rows and len(rows) > 1:
                                    rows = rows[:-1]  # exclude forming candle
                                candles = [
                                    Candle(
                                        symbol=sym.upper(),
                                        open_time_ms=int(row[0]),
                                        close_time_ms=int(row[6]),
                                        open=float(row[1]), high=float(row[2]),
                                        low=float(row[3]), close=float(row[4]),
                                        volume=float(row[5]), is_closed=True,
                                    )
                                    for row in rows
                                ]
                                state.md.seed_window(sym.upper(), new_cfg.timeframe, candles)
                                log.info("Seeded %d candles for new symbol %s", len(candles), sym)
                            except Exception:
                                log.warning("Could not seed candles for %s", sym, exc_info=True)

                # 4. Hot-swap WebSocket streams (stop removed, start added)
                await state.md.update_symbols(new_trade_list)

                # 5. Compute initial signals for newly added symbols
                if state.strategy and state.manager and state.adapter and added_symbols:
                    equity = await state.adapter.get_equity_usd()
                    for sym in added_symbols:
                        try:
                            window = state.md.get_window(sym)
                            if not window:
                                continue
                            current_price = state.md.get_current_price(sym)
                            sym_state = state.manager.get_state(sym)
                            desired = state.strategy.compute(
                                sym, {new_cfg.timeframe: window},
                                sym_state.position_state, current_price,
                            )
                            await state.manager.apply_desired(desired, equity=equity)
                            log.info("Computed initial signal for %s", sym)
                        except Exception:
                            log.warning("Failed initial signal for %s", sym, exc_info=True)

            # ── Persist config to YAML file ──────────────────
            if state.config_path:
                try:
                    import yaml
                    cfg_dict = new_cfg.model_dump()
                    # Strip env-sourced secrets that should NOT be written to YAML
                    cfg_dict.get("database", {}).pop("url", None)
                    for secret_key in ("jwt_secret", "admin_username", "admin_password"):
                        cfg_dict.get("auth", {}).pop(secret_key, None)
                    state.config_path.write_text(
                        yaml.dump(cfg_dict, default_flow_style=False, sort_keys=False, allow_unicode=True),
                        encoding="utf-8",
                    )
                    log.info("Config persisted to %s", state.config_path)
                except Exception:
                    log.warning("Failed to persist config to YAML", exc_info=True)

            return {"applied": True, "message": "Config saved and applied to running engine"}

    # ─── Equity ──────────────────────────────────────

    @router.get("/equity", dependencies=auth_dep)
    async def get_equity() -> dict[str, float]:
        _require_ready()
        if state.adapter is None:
            raise HTTPException(status_code=503, detail="Engine not ready")
        hit, cached = _equity_cache.get()
        if hit:
            return cached
        equity = await state.adapter.get_equity_usd()
        return _equity_cache.set({"equity_usd": equity})

    @router.get("/equity/history", response_model=list[EquitySnapshotResponse], dependencies=auth_dep)
    async def get_equity_history(limit: int = 100) -> list[EquitySnapshotResponse]:
        if state.repo is None:
            raise HTTPException(status_code=503, detail="DB not ready")
        snaps = await state.repo.get_equity_snapshots(limit)
        return [EquitySnapshotResponse(**s) for s in snaps]

    # ─── Trades ──────────────────────────────────────

    @router.get("/trades", response_model=list[TradeResponse], dependencies=auth_dep)
    async def get_trades(symbol: str | None = None, limit: int = 50) -> list[TradeResponse]:
        if state.repo is None:
            raise HTTPException(status_code=503, detail="DB not ready")
        trades = await state.repo.get_trades(symbol, limit)
        return [
            TradeResponse(
                id=t.id, symbol=t.symbol, side=t.side,
                entry_price=t.entry_price, exit_price=t.exit_price,
                quantity=t.quantity, realized_pnl=t.realized_pnl,
                fees=t.fees, funding_cost=t.funding_cost,
                exit_reason=t.exit_reason,
                entry_time_ms=t.entry_time_ms, exit_time_ms=t.exit_time_ms,
            )
            for t in trades
        ]

    @router.delete("/trades", dependencies=auth_dep)
    async def clear_trades() -> dict[str, Any]:
        """Delete all trade history from the database."""
        if state.repo is None:
            raise HTTPException(status_code=503, detail="DB not ready")
        count = await state.repo.clear_trades()
        return {"message": f"Cleared {count} trades from history", "deleted": count}

    # ─── Positions ───────────────────────────────────

    @router.get("/positions/open", response_model=list[PositionResponse], dependencies=auth_dep)
    async def get_open_positions() -> list[PositionResponse]:
        _require_ready()
        if state.config is None or state.adapter is None:
            raise HTTPException(status_code=503, detail="Engine not ready")
        hit, cached = _positions_cache.get()
        if hit:
            return cached
        result = []
        for symbol in state.config.trade_list:
            pos = await state.adapter.get_position(symbol)
            if pos.side is None or pos.quantity == 0:
                continue

            mark = state.md.get_current_price(symbol) if state.md else 0.0
            if pos.side == OrderSide.BUY:
                upnl = (mark - pos.entry_price) * pos.quantity
            else:
                upnl = (pos.entry_price - mark) * pos.quantity

            sym_status = state.manager.get_symbol_status(symbol) if state.manager else {}
            result.append(PositionResponse(
                symbol=pos.symbol, side=pos.side.value,
                quantity=pos.quantity, entry_price=pos.entry_price,
                mark_price=mark, unrealized_pnl=round(upnl, 4),
                sl_price=sym_status.get("sl_price", 0) or 0,
                tp_price=sym_status.get("tp_price", 0) or 0,
                trailing_active=sym_status.get("trailing_active", False),
                trailing_watermark=sym_status.get("trailing_watermark", 0),
                opened_at_ms=pos.opened_at_ms,
            ))
        return _positions_cache.set(result)

    # ─── Orders ──────────────────────────────────────

    @router.get("/orders/open-all", response_model=list[OrderResponse], dependencies=auth_dep)
    async def get_all_open_orders() -> list[OrderResponse]:
        _require_ready()
        if state.config is None or state.adapter is None:
            raise HTTPException(status_code=503, detail="Engine not ready")
        hit, cached = _orders_cache.get()
        if hit:
            return cached
        all_orders = []
        orders = await state.adapter.get_all_open_orders()
        # Filter strictly by watchlist since it pulls the whole account
        watchlist_set = set(state.config.watchlist)
        for o in orders:
            if o.symbol in watchlist_set:
                all_orders.append(OrderResponse(
                    order_id=o.order_id, symbol=o.symbol,
                    side=o.side.value, order_type=o.order_type.value,
                    stop_price=o.stop_price, quantity=o.quantity,
                    status=o.status.value, reduce_only=o.reduce_only, tag=o.tag,
                ))
        return _orders_cache.set(all_orders)

    # ─── PnL ─────────────────────────────────────────

    @router.get("/pnl/today", response_model=PnlResponse, dependencies=auth_dep)
    async def get_pnl() -> PnlResponse:
        if state.repo is None:
            raise HTTPException(status_code=503, detail="DB not ready")
        pnl = await state.repo.get_todays_realized_pnl()
        hw = await state.repo.get_equity_high_water()
        losses = await state.repo.get_consecutive_losses()
        return PnlResponse(realized_pnl_today=pnl, equity_high_water=hw, consecutive_losses=losses)

    # ─── Actions ─────────────────────────────────────

    @router.post("/close-all", response_model=CloseAllResponse, dependencies=auth_dep)
    async def close_all() -> CloseAllResponse:
        _require_ready()
        if state.config is None or state.adapter is None:
            raise HTTPException(status_code=503, detail="Engine not ready")
        cancelled = 0
        closed = 0
        # Use trade_list (only symbols with active orders), not watchlist
        for symbol in state.config.trade_list:
            if state.manager:
                await state.manager.clear_state(symbol)
            # Clear strategy fixed levels so resume computes fresh HH/LL
            if state.strategy:
                state.strategy.clear_state(symbol)
            orders = await state.adapter.get_open_orders(symbol)
            for o in orders:
                await state.adapter.cancel_order(symbol, o.order_id)
                cancelled += 1
            pos = await state.adapter.get_position(symbol)
            if pos.side is not None and pos.quantity > 0:
                close_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                await state.adapter.place_order(OrderIntent(
                    symbol=symbol, side=close_side, order_type=OrderType.MARKET,
                    stop_price=None, quantity=pos.quantity,
                    reduce_only=True, tag="manual_close_all",
                ))
                closed += 1
        # Only pause if not already paused (prevents "paused → paused" warnings)
        if state.state_machine and state.state_machine.is_running:
            state.state_machine.pause("manual close-all")
        return CloseAllResponse(cancelled_orders=cancelled, closed_positions=closed)

    @router.post("/pause", response_model=MessageResponse, dependencies=auth_dep)
    async def pause_trading() -> MessageResponse:
        if state.state_machine:
            state.state_machine.pause("manual pause")
        return MessageResponse(message="Trading paused.")

    @router.post("/resume", response_model=MessageResponse, dependencies=auth_dep)
    async def resume_trading() -> MessageResponse:
        if state.adapter is None or state.config is None:
            raise HTTPException(status_code=503, detail="Engine not ready")

        # Handle state transitions — resume from PAUSED, or no-op if already RUNNING
        sm = state.state_machine
        if sm:
            if sm.is_running:
                pass  # already running, just recompute signals below
            else:
                if not sm.resume("manual resume"):
                    log.warning("Resume failed from state: %s", sm.status.value)

        # Re-compute signals for all traded symbols
        placed = 0
        errors = []
        if state.md and state.manager and state.strategy:
            for symbol in state.config.trade_list:
                try:
                    window = state.md.get_window(symbol)
                    if not window:
                        continue
                    state.strategy.clear_state(symbol)
                    current_price = state.md.get_current_price(symbol)
                    sym_state = state.manager.get_state(symbol)
                    desired = state.strategy.compute(
                        symbol, {state.config.timeframe: window},
                        sym_state.position_state, current_price,
                    )
                    equity = await state.adapter.get_equity_usd()
                    await state.manager.apply_desired(desired, equity=equity)
                    placed += 1
                except Exception as e:
                    log.exception("Resume: error processing %s", symbol)
                    errors.append(f"{symbol}: {e}")

        msg = f"Resumed. Placed orders for {placed} symbols."
        if errors:
            msg += f" Errors: {'; '.join(errors)}"
        return MessageResponse(message=msg)

    @router.post("/reset", response_model=MessageResponse, dependencies=auth_dep)
    async def reset() -> MessageResponse:
        _require_ready()
        if state.config is None or state.adapter is None:
            raise HTTPException(status_code=503, detail="Engine not ready")
        # Close everything
        for symbol in state.config.trade_list:
            if state.manager:
                await state.manager.clear_state(symbol)
            await state.adapter.cancel_all_orders(symbol)
            pos = await state.adapter.get_position(symbol)
            if pos.side is not None and pos.quantity > 0:
                close_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                await state.adapter.place_order(OrderIntent(
                    symbol=symbol, side=close_side, order_type=OrderType.MARKET,
                    stop_price=None, quantity=pos.quantity,
                    reduce_only=True, tag="reset",
                ))
        # Wipe DB
        if state.repo:
            await state.repo.reset_all()
        # Reset simulator equity
        if hasattr(state.adapter, '_equity') and hasattr(state.adapter, 'cfg'):
            state.adapter._equity = state.adapter.cfg.starting_equity_usd  # type: ignore
            if hasattr(state.adapter, '_positions'):
                state.adapter._positions.clear()  # type: ignore
        if state.state_machine:
            state.state_machine.pause("reset")
        return MessageResponse(message="All data cleared. Engine paused.")

    # ─── Scanner ─────────────────────────────────────

    @router.post("/scan", dependencies=auth_dep)
    async def run_scan() -> dict[str, Any]:
        _require_ready()
        if state.md is None or state.config is None or state.repo is None:
            raise HTTPException(status_code=503, detail="Not ready")
        
        import httpx
        import asyncio
        from dashrock.core.types import Candle
        from dashrock.market.scanner import rank_symbols

        candle_data: dict[str, list[Candle]] = {}
        interval = state.config.timeframe
        base = "https://fapi.binance.com/fapi/v1/klines"

        async def fetch_symbol(client: httpx.AsyncClient, sym: str) -> None:
            try:
                r = await client.get(base, params={"symbol": sym.upper(), "interval": interval, "limit": 100})
                if r.status_code == 200:
                    rows = r.json()
                    if rows and len(rows) > 1:
                        rows = rows[:-1]  # Exclude unclosed current candle
                    candle_data[sym] = [
                        Candle(
                            symbol=sym.upper(),
                            open_time_ms=int(row[0]), close_time_ms=int(row[6]),
                            open=float(row[1]), high=float(row[2]),
                            low=float(row[3]), close=float(row[4]),
                            volume=float(row[5]), is_closed=True,
                        ) for row in rows
                    ]
            except Exception as e:
                log.warning("Scanner fetch failed for %s: %s", sym, e)

        async with httpx.AsyncClient(timeout=10) as client:
            tasks = [fetch_symbol(client, sym) for sym in state.config.watchlist]
            await asyncio.gather(*tasks)

        rankings = rank_symbols(candle_data, state.config.volatility)
        for r in rankings:
            await state.repo.insert_scanner_snapshot(
                symbol=r.symbol, score=r.score, natr=r.natr,
                expansion=r.expansion, donchian_atr_ratio=r.donchian_atr_ratio,
            )
        return {
            "ranked": len(rankings),
            "results": [
                {"symbol": r.symbol, "score": r.score, "natr": r.natr}
                for r in rankings
            ],
        }

    # ─── Candles ──────────────────────────────────────

    @router.get("/levels/{symbol}", dependencies=auth_dep)
    async def get_levels(symbol: str) -> dict[str, Any]:
        """Return active order/position price levels for chart overlay."""
        sym = symbol.upper()
        levels = []
        if state.manager:
            s = state.manager.get_state(sym)
            is_native = (state.config and state.config.trailing.enabled
                         and state.config.trailing.mode == "binance_native")
            if s.entry_buy_stop_price:
                levels.append({"price": s.entry_buy_stop_price, "color": "#10b981", "title": "Buy Stop", "style": 2})
            if s.entry_sell_stop_price:
                levels.append({"price": s.entry_sell_stop_price, "color": "#ef4444", "title": "Sell Stop", "style": 2})
            if s.sl_price:
                sl_label = "Emergency SL" if is_native else "Stop Loss"
                levels.append({"price": s.sl_price, "color": "#f59e0b", "title": sl_label, "style": 1})
            if s.tp_price:
                levels.append({"price": s.tp_price, "color": "#3b82f6", "title": "Take Profit", "style": 1})
            if s.entry_price:
                levels.append({"price": s.entry_price, "color": "#8b5cf6", "title": "Entry", "style": 0})
            # In binance_native mode, trailing watermark is managed by Binance (stale locally)
            # Show activation price instead
            if is_native and s.has_position and s.tsl_id:
                # Calculate activation price the same way as entry fill
                from dashrock.core.types import PositionState
                act_pct = state.config.trailing.activation_pips / 100
                if s.position_state == PositionState.LONG:
                    act_price = s.entry_price * (1 + act_pct)
                else:
                    act_price = s.entry_price * (1 - act_pct)
                act_price = state.manager._registry.round_price(sym, act_price)
                levels.append({"price": act_price, "color": "#ec4899", "title": "TSL Activate", "style": 2})
            elif not is_native and s.trailing_watermark:
                levels.append({"price": s.trailing_watermark, "color": "#ec4899", "title": "Trail HW", "style": 2})
        return {"symbol": sym, "levels": levels}

    @router.get("/candles/{symbol}", dependencies=auth_dep)
    async def get_candles(symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        if state.md is None:
            raise HTTPException(status_code=503, detail="Market data not ready")
        sym = symbol.upper()
        window = state.md.get_window(sym)
        candles = window[-limit:] if len(window) > limit else window
        result = [
            {"time": c.open_time_ms // 1000, "open": c.open, "high": c.high, "low": c.low, "close": c.close}
            for c in candles
        ]
        live = state.md.get_live_candle(sym)
        if live:
            live_time = live.open_time_ms // 1000
            # Only append if timestamp is strictly after the last closed candle.
            # This prevents duplicate timestamps that crash lightweight-charts.
            if not result or live_time > result[-1]["time"]:
                result.append({"time": live_time, "open": live.open, "high": live.high, "low": live.low, "close": live.close})
            elif result and live_time == result[-1]["time"]:
                # Same timestamp — update in place (live data is more current)
                result[-1] = {"time": live_time, "open": live.open, "high": live.high, "low": live.low, "close": live.close}
        return result

    # ─── Symbols ─────────────────────────────────────

    @router.get("/watchlist", dependencies=auth_dep)
    async def get_watchlist() -> dict[str, Any]:
        if state.config is None:
            raise HTTPException(status_code=503, detail="Config not loaded")
        return {
            "symbols": state.config.watchlist,
            "trade_list": state.config.trade_list,
            "timeframe": state.config.timeframe,
        }

    # ─── Binance Position Mode ───────────────────────

    @router.get("/position-mode", dependencies=auth_dep)
    async def get_position_mode() -> dict[str, Any]:
        """Read the current Binance position mode (one-way vs hedge)."""
        _require_ready()
        from dashrock.adapters.binance_live import BinanceLiveAdapter
        if not isinstance(state.adapter, BinanceLiveAdapter):
            return {"hedge_mode": False, "source": "simulator"}
        try:
            is_hedge = await state.adapter.get_position_mode()
            return {"hedge_mode": is_hedge, "source": "exchange"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/position-mode", dependencies=auth_dep)
    async def set_position_mode(body: PositionModeRequest) -> dict[str, Any]:
        """Toggle Binance position mode. Requires no open positions/orders.

        Body: {"hedge_mode": true/false}
        """
        _require_ready()
        from dashrock.adapters.binance_live import BinanceLiveAdapter
        if not isinstance(state.adapter, BinanceLiveAdapter):
            raise HTTPException(status_code=400, detail="Only available in live/testnet mode")

        hedge = body.hedge_mode
        try:
            await state.adapter.set_position_mode(hedge)
            mode_str = "Hedge Mode" if hedge else "One-Way Mode"
            return {"message": f"Position mode changed to {mode_str}", "hedge_mode": hedge}
        except Exception as e:
            error_msg = str(e)
            if "-4059" in error_msg or "position side" in error_msg.lower():
                raise HTTPException(
                    status_code=400,
                    detail="Cannot change position mode while you have open positions or orders. Close everything first.",
                )
            raise HTTPException(status_code=500, detail=error_msg)

    return router
