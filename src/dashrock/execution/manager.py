"""Execution manager — order lifecycle with persistent state.

This is the heart of the trading engine. Manages:
- Entry order placement (idempotent reconciliation with desired orders)
- SL/TP placement on fill
- Trailing stop management (delegated to trailing module)
- Opposite order policy enforcement
- Cooldown tracking (persisted)
- State persistence to DB on every change (crash recovery)

Key improvements over v1:
- All state persisted to PostgreSQL (survives crashes)
- SL price cached in state (no more N+1 API queries per tick)
- Clean delegation to trailing/cooldown sub-modules
- Emits events to EventBus for notifications
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from dashrock.adapters.base import ExecutionAdapter, ExchangeError, OrderNotFoundError
from dashrock.config import Config
from dashrock.core.events import (
    EventBus,
    FillEvent,
    OrderCancelled,
    OrderPlaced,
    PositionClosed,
    PositionOpened,
)
from dashrock.core.types import (
    DesiredOrders,
    ExitReason,
    Fill,
    LiveOrder,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionState,
    SymbolExecutionState,
    TradeRecord,
)
from dashrock.execution.trailing import TrailingManager
from dashrock.market.symbol_registry import SymbolRegistry
from dashrock.persistence.repositories import Repository
from dashrock.risk.position_sizer import size_for_risk
from dashrock.utils.time_filter import BlackoutDecision

log = logging.getLogger(__name__)


class ExecutionManager:
    """Manages order lifecycle for all traded symbols."""

    def __init__(
        self,
        *,
        adapter: ExecutionAdapter,
        config: Config,
        repo: Repository,
        bus: EventBus,
        registry: SymbolRegistry,
    ) -> None:
        self._adapter = adapter
        self._cfg = config
        self._repo = repo
        self._bus = bus
        self._registry = registry
        self._states: dict[str, SymbolExecutionState] = {}
        self._trailing = TrailingManager(config.trailing)
        self._last_tick_time: dict[str, float] = {}  # throttle trailing updates
        self._tick_locks: dict[str, asyncio.Lock] = {}  # prevent concurrent trailing

    # ─── State Management ────────────────────────────────

    def get_state(self, symbol: str) -> SymbolExecutionState:
        if symbol not in self._states:
            self._states[symbol] = SymbolExecutionState(symbol=symbol)
        return self._states[symbol]

    async def _persist_state(self, symbol: str) -> None:
        """Save state to DB after every change."""
        state = self.get_state(symbol)
        await self._repo.save_engine_state(state)

    async def load_persisted_states(self) -> None:
        """Restore states from DB on startup (crash recovery)."""
        states = await self._repo.load_engine_states()
        self._states.update(states)
        if states:
            log.info("Restored execution state for %d symbols", len(states))
            for sym, s in states.items():
                log.info(
                    "  %s: %s qty=%.8g entry=%.8g sl=%s tp=%s",
                    sym, s.position_state.value, s.position_qty, s.entry_price,
                    s.sl_price, s.tp_price,
                )

    def get_symbol_status(self, symbol: str) -> dict:
        s = self.get_state(symbol)
        return {
            "position_state": s.position_state.value,
            "entry_price": s.entry_price,
            "position_qty": s.position_qty,
            "sl_id": s.sl_id,
            "sl_price": s.sl_price,
            "tsl_id": s.tsl_id,
            "tp_id": s.tp_id,
            "tp_price": s.tp_price,
            "trailing_active": self._trailing.is_active(symbol),
            "trailing_watermark": s.trailing_watermark,
            "cooldown_remaining": s.cooldown_remaining,
        }

    async def clear_state(self, symbol: str) -> None:
        self._states[symbol] = SymbolExecutionState(symbol=symbol)
        await self._repo.clear_engine_state(symbol)

    async def clear_all_state(self) -> None:
        self._states.clear()
        await self._repo.clear_all_engine_states()

    # ─── Core: Apply Desired Orders ──────────────────────

    async def apply_desired(
        self,
        desired: DesiredOrders,
        equity: float = 0.0,
        blackout: BlackoutDecision | None = None,
    ) -> None:
        """Reconcile current orders with what the strategy wants.

        Idempotent: if the desired stop prices match existing orders, no action.
        """
        symbol = desired.symbol
        state = self.get_state(symbol)

        # Skip if in cooldown
        if state.cooldown_remaining > 0:
            state.cooldown_remaining -= 1
            log.info("Skipping %s — cooldown remaining: %d candles", symbol, state.cooldown_remaining)
            await self._persist_state(symbol)
            return

        # Skip if position already open (entry orders not needed)
        if state.has_position:
            log.debug("Skipping %s — position already open (%s)", symbol, state.position_state.value)
            return

        # Skip during blackout
        if blackout and not blackout.allow_new_entries:
            log.info("Skipping %s — in blackout period", symbol)
            return

        log.info(
            "Applying desired orders for %s: buy_stop=%s sell_stop=%s equity=%.2f",
            symbol,
            f"%.8g" % desired.buy_stop.stop_price if desired.buy_stop else "None",
            f"%.8g" % desired.sell_stop.stop_price if desired.sell_stop else "None",
            equity,
        )

        # Handle buy stop
        await self._reconcile_entry(
            state, "buy", desired.buy_stop, equity, desired.reference_price,
        )

        # Handle sell stop
        await self._reconcile_entry(
            state, "sell", desired.sell_stop, equity, desired.reference_price,
        )

        await self._persist_state(symbol)

    async def _reconcile_entry(
        self,
        state: SymbolExecutionState,
        side_label: str,  # "buy" or "sell"
        intent: OrderIntent | None,
        equity: float,
        reference_price: float,
    ) -> None:
        """Ensure the correct entry order exists for one side."""
        current_id = state.entry_buy_id if side_label == "buy" else state.entry_sell_id
        current_price = state.entry_buy_stop_price if side_label == "buy" else state.entry_sell_stop_price

        if intent is None:
            # Strategy doesn't want this side — cancel if exists
            if current_id:
                log.info("Cancelling %s entry for %s — strategy no longer wants it", side_label, state.symbol)
                await self._safe_cancel(state.symbol, current_id)
                if side_label == "buy":
                    state.entry_buy_id = None
                    state.entry_buy_stop_price = None
                else:
                    state.entry_sell_id = None
                    state.entry_sell_stop_price = None
            return

        # If existing order at same price, keep it
        if current_id and current_price == intent.stop_price:
            log.debug("Keeping existing %s entry for %s at %.8g", side_label, state.symbol, current_price)
            return

        # Cancel old order if price changed
        if current_id:
            log.info("Replacing %s entry for %s — price changed from %.8g to %.8g",
                     side_label, state.symbol, current_price, intent.stop_price)
            await self._safe_cancel(state.symbol, current_id)

        # Size the position
        sl_price = self._calculate_sl_price(intent)
        qty = size_for_risk(
            self._cfg.sizing, equity, intent.stop_price or 0, sl_price,
        )
        if qty <= 0:
            log.warning(
                "Skipping %s entry for %s — qty=0 (equity=%.2f entry=%.8g sl=%.8g)",
                side_label, state.symbol, equity, intent.stop_price or 0, sl_price,
            )
            return

        # Round quantity and validate
        qty = self._registry.round_qty(state.symbol, qty)
        if qty <= 0:
            log.warning(
                "Skipping %s entry for %s — qty rounded to 0 (min step too large)",
                side_label, state.symbol,
            )
            return
        price = self._registry.round_price(state.symbol, intent.stop_price or 0)
        validation = self._registry.validate_order(state.symbol, qty, price)
        if validation:
            log.warning("Order rejected by validation: %s", validation)
            return

        # Place the order
        sized_intent = OrderIntent(
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            stop_price=price,
            quantity=qty,
            reduce_only=intent.reduce_only,
            tag=intent.tag,
        )
        try:
            order = await self._adapter.place_order(sized_intent)
            await self._bus.publish(OrderPlaced(order=order))
        except ExchangeError as e:
            if e.code == -2021:
                # Price blew past the entry stop before the order landed.
                # This is a fast-market skip, not an error — the opposite
                # direction entry order will still be placed normally.
                log.info(
                    "MISSED BREAKOUT: %s %s entry @ %.8g — price already moved past "
                    "stop (fast market). Skipping this direction.",
                    side_label.upper(), state.symbol, price,
                )
            else:
                log.error("Failed to place order for %s: %s", state.symbol, e)
            return
        except Exception as e:
            log.error("Failed to place order for %s: %s", state.symbol, e)
            return
        if not order:
            return

        log.info(
            "PLACED %s entry %s @ %.8g qty=%.8g (SL=%.8g)",
            side_label.upper(), state.symbol, price, qty, sl_price,
        )

        # Update state
        if side_label == "buy":
            state.entry_buy_id = order.order_id
            state.entry_buy_stop_price = price
        else:
            state.entry_sell_id = order.order_id
            state.entry_sell_stop_price = price

        # Record in DB
        await self._repo.insert_order(
            order_id=order.order_id, symbol=order.symbol,
            side=order.side.value, order_type=order.order_type.value,
            stop_price=order.stop_price, quantity=order.quantity,
            status=order.status.value, reduce_only=order.reduce_only,
            tag=order.tag, created_at_ms=int(time.time() * 1000),
        )
        # Note: OrderPlaced event already emitted by _safe_place_order

    def _calculate_sl_price(self, intent: OrderIntent) -> float:
        """Calculate the SL price based on entry price and config."""
        entry = intent.stop_price or 0
        if entry <= 0:
            return 0
        if self._cfg.stops.use_pct_pips:
            sl_distance = entry * (self._cfg.stops.sl_pips / 100.0)
        else:
            sl_distance = self._cfg.stops.sl_pips
        if intent.side == OrderSide.BUY:
            return entry - sl_distance
        else:
            return entry + sl_distance

    # ─── Fill Handling ───────────────────────────────────

    async def on_fill(self, fill: Fill) -> None:
        """Route a fill to the correct handler (entry or exit).

        Fill matching strategy (in order):
        1. Match by order_id against stored entry/SL/TP/TSL IDs
        2. Match by tag prefix (e.g., "entry_buy_stop", "sl_emergency_")
        3. FALLBACK: Context-based matching by position state + fill side
           (critical for LIVE Binance where algo orders create child orders
            with different IDs that don't match stored algoId)
        """
        state = self.get_state(fill.symbol)
        await self._bus.publish(FillEvent(fill=fill))

        # ── Strategy 1 & 2: Match by order_id or tag ──
        is_entry_by_id = fill.order_id in (
            state.entry_buy_id, state.entry_sell_id, state.pending_reversal_id,
        )
        is_entry_by_tag = fill.tag.startswith(("entry_buy_stop", "entry_sell_stop"))

        is_exit_by_id = fill.order_id in (state.sl_id, state.tsl_id, state.tp_id)
        is_exit_by_tag = fill.tag.startswith((
            "sl", "tp", "trailing_sl", "reversal_close_only", "native_tsl_",
        ))

        # ── Strategy 3: Context-based fallback (for live algo child orders) ──
        is_entry_by_context = False
        is_exit_by_context = False

        if not (is_entry_by_id or is_entry_by_tag or is_exit_by_id or is_exit_by_tag):
            # No ID/tag match — try context-based inference
            if not state.has_position:
                # Symbol is FLAT: check if fill side matches a pending entry
                if fill.side == OrderSide.BUY and state.entry_buy_id:
                    is_entry_by_context = True
                    log.info(
                        "CONTEXT MATCH: %s BUY fill (id=%s) → entry (pending buy_id=%s)",
                        fill.symbol, fill.order_id, state.entry_buy_id,
                    )
                elif fill.side == OrderSide.SELL and state.entry_sell_id:
                    is_entry_by_context = True
                    log.info(
                        "CONTEXT MATCH: %s SELL fill (id=%s) → entry (pending sell_id=%s)",
                        fill.symbol, fill.order_id, state.entry_sell_id,
                    )
            else:
                # Symbol HAS a position: check if fill is on the closing side
                exit_side = (
                    OrderSide.SELL if state.position_state == PositionState.LONG
                    else OrderSide.BUY
                )
                if fill.side == exit_side:
                    is_exit_by_context = True
                    # Determine exit reason from remaining orders
                    exit_reason = "unknown"
                    if state.sl_id:
                        exit_reason = "sl/tsl"
                    if state.tsl_id:
                        exit_reason = "tsl"
                    log.info(
                        "CONTEXT MATCH: %s %s fill (id=%s) → exit (%s)",
                        fill.symbol, fill.side.value, fill.order_id, exit_reason,
                    )

        # ── Route to handler ──
        if is_entry_by_id or is_entry_by_tag or is_entry_by_context:
            # Guard: if position is already open and an opposite entry fills
            # (race condition — cancel didn't reach Binance in time), treat it
            # as a conflict. Cancel the stale TSL/SL, close the old position
            # at market via exit handler, THEN open the new one.
            if state.has_position:
                log.warning(
                    "RACE CONDITION: %s entry fill while already %s — closing old position first",
                    fill.symbol, state.position_state.value,
                )
                # Cancel old SL/TP/TSL (including native TSL)
                for order_id in [state.sl_id, state.tsl_id, state.tp_id]:
                    if order_id:
                        await self._safe_cancel(fill.symbol, order_id)

                # Send a REAL market order to Binance to close the old position
                # (critical in hedge mode — synthetic exits don't touch the exchange)
                close_side = OrderSide.SELL if state.position_state == PositionState.LONG else OrderSide.BUY
                close_qty = self._registry.round_qty(fill.symbol, state.position_qty)
                try:
                    close_result = await self._adapter.place_order(OrderIntent(
                        symbol=fill.symbol,
                        side=close_side,
                        order_type=OrderType.MARKET,
                        stop_price=None,
                        quantity=close_qty,
                        reduce_only=True,
                        tag=f"race_close_{int(time.time()*1000)}",
                    ))
                    log.info(
                        "RACE CONDITION: sent market close %s %s qty=%.8g → %s",
                        fill.symbol, close_side.value, close_qty,
                        close_result.order_id if close_result else "FAILED",
                    )
                except Exception:
                    log.exception("RACE CONDITION: failed to close old %s position on exchange", fill.symbol)

                # Process exit in engine state (use fill price as approximate close)
                synthetic_exit = Fill(
                    symbol=fill.symbol,
                    order_id="race_condition_close",
                    side=close_side,
                    price=fill.price,
                    quantity=state.position_qty,
                    fee=0.0,
                    timestamp_ms=fill.timestamp_ms,
                    tag="sl_race_condition",
                )
                await self._handle_exit_fill(state, synthetic_exit)

            await self._handle_entry_fill(state, fill)
        elif is_exit_by_id or is_exit_by_tag or is_exit_by_context:
            await self._handle_exit_fill(state, fill)
        else:
            log.warning("Unknown fill for %s order_id=%s tag=%s", fill.symbol, fill.order_id, fill.tag)

    async def _handle_entry_fill(self, state: SymbolExecutionState, fill: Fill) -> None:
        """Position opened — place SL + TP, handle opposite order."""
        log.info(
            "ENTRY FILL: %s %s @ %.8g qty=%.8g fee=%.6f",
            fill.symbol, fill.side.value, fill.price, fill.quantity, fill.fee,
        )

        # Update state
        state.position_state = PositionState.LONG if fill.side == OrderSide.BUY else PositionState.SHORT
        state.position_qty = fill.quantity
        state.entry_price = fill.price
        state.entry_time_ms = fill.timestamp_ms
        state.entry_fee = fill.fee
        state.trailing_watermark = fill.price

        # Clear entry order references
        if fill.order_id == state.entry_buy_id or fill.tag.startswith("entry_buy_stop"):
            state.entry_buy_id = None
            state.entry_buy_stop_price = None
        elif fill.order_id == state.entry_sell_id or fill.tag.startswith("entry_sell_stop"):
            state.entry_sell_id = None
            state.entry_sell_stop_price = None

        # Handle opposite pending order
        await self._handle_opposite_order(state, fill)

        # Place SL — different logic for binance_native vs custom trailing
        sl_side = OrderSide.SELL if fill.side == OrderSide.BUY else OrderSide.BUY

        if self._cfg.trailing.enabled and self._cfg.trailing.mode == "binance_native":
            # ── Binance Native Trailing Stop + Fixed Emergency SL ──
            # Two orders: fixed SL for downside protection + trailing for profit locking.
            callback_rate = self._cfg.trailing.stop_pips  # maps directly to callbackRate %

            # 1. Place FIXED emergency SL first (uses sl_pips from stops config)
            emergency_sl_price = self._calculate_sl_price(OrderIntent(
                symbol=fill.symbol, side=fill.side,
                order_type=OrderType.STOP_MARKET,
                stop_price=fill.price, quantity=0,
            ))
            emergency_sl_price = self._registry.round_price(fill.symbol, emergency_sl_price)

            # Retry up to 3 times — transient exchange errors can be retried.
            # -2021 (would immediately trigger) is NOT transient: the price has
            # already moved past the SL level — close at market immediately.
            emergency_sl = None
            sl_immediately_triggered = False
            for attempt in range(1, 4):
                try:
                    order = await self._adapter.place_order(OrderIntent(
                        symbol=fill.symbol, side=sl_side,
                        order_type=OrderType.STOP_MARKET,
                        stop_price=emergency_sl_price, quantity=fill.quantity,
                        reduce_only=True, tag=f"sl_emergency_{int(time.time()*1000)}",
                    ))
                    await self._bus.publish(OrderPlaced(order=order))
                    emergency_sl = order
                    break
                except ExchangeError as e:
                    if e.code == -2021:
                        # Price already breached SL — close at market immediately
                        log.warning(
                            "EMERGENCY SL -2021 for %s: price already past SL %.8g "
                            "— closing position at market",
                            fill.symbol, emergency_sl_price,
                        )
                        sl_immediately_triggered = True
                        break
                    log.warning(
                        "EMERGENCY SL attempt %d/3 failed for %s — retrying in 500ms",
                        attempt, fill.symbol,
                    )
                    await asyncio.sleep(0.5)
                except Exception:
                    log.warning(
                        "EMERGENCY SL attempt %d/3 failed for %s — retrying in 500ms",
                        attempt, fill.symbol,
                    )
                    await asyncio.sleep(0.5)

            if sl_immediately_triggered:
                # SL level already breached — send a market close now
                log.error(
                    "EMERGENCY MARKET CLOSE: %s SL level %.8g already breached — closing at market",
                    fill.symbol, emergency_sl_price,
                )
                try:
                    close_order = await self._adapter.place_order(OrderIntent(
                        symbol=fill.symbol, side=sl_side,
                        order_type=OrderType.MARKET,
                        stop_price=None, quantity=fill.quantity,
                        reduce_only=True, tag=f"sl_market_close_{int(time.time()*1000)}",
                    ))
                    log.info(
                        "EMERGENCY MARKET CLOSE sent for %s → order %s",
                        fill.symbol, close_order.order_id if close_order else "?",
                    )
                except Exception:
                    log.exception("EMERGENCY MARKET CLOSE failed for %s!", fill.symbol)
                # State will be updated when the market close fill arrives
                # via context-based fill matching
                state.sl_price = emergency_sl_price
            elif emergency_sl:
                state.sl_id = emergency_sl.order_id
                state.sl_price = emergency_sl_price
                log.info(
                    "EMERGENCY SL placed: %s @ %.8g (%.2f%% from entry)",
                    fill.symbol, emergency_sl_price, self._cfg.stops.sl_pips,
                )

            # 2. Place native trailing stop (for profit protection once activated)
            activate_price = None
            if self._cfg.trailing.activation_pips > 0:
                if fill.side == OrderSide.BUY:  # LONG — activate when price rises
                    activate_price = fill.price * (1 + self._cfg.trailing.activation_pips / 100.0)
                else:  # SHORT — activate when price drops
                    activate_price = fill.price * (1 - self._cfg.trailing.activation_pips / 100.0)
                activate_price = self._registry.round_price(fill.symbol, activate_price)

            tsl_order = await self._safe_place_order(OrderIntent(
                symbol=fill.symbol, side=sl_side,
                order_type=OrderType.TRAILING_STOP_MARKET,
                stop_price=None, quantity=fill.quantity,
                reduce_only=True,
                callback_rate=callback_rate,
                activate_price=activate_price,
                tag=f"native_tsl_{int(time.time()*1000)}",
            ))
            if tsl_order:
                state.tsl_id = tsl_order.order_id
                log.info(
                    "NATIVE TSL placed: %s callback=%.2f%% activate=%s",
                    fill.symbol, callback_rate,
                    f"{activate_price:.8g}" if activate_price else "immediate",
                )
                from dashrock.core.events import NativeTrailingPlaced
                await self._bus.publish(NativeTrailingPlaced(
                    symbol=fill.symbol,
                    callback_rate=callback_rate,
                    activate_price=activate_price,
                    order_id=tsl_order.order_id,
                ))
            else:
                log.warning("Native TSL failed for %s — relying on emergency SL only", fill.symbol)
        else:
            # ── Custom Trailing (step / activation_trail) ──
            sl_price = self._calculate_sl_price(
                OrderIntent(
                    symbol=fill.symbol, side=fill.side,
                    order_type=OrderType.STOP_MARKET,
                    stop_price=fill.price, quantity=0,
                )
            )
            sl_price = self._registry.round_price(fill.symbol, sl_price)
            sl_order = await self._safe_place_order(OrderIntent(
                symbol=fill.symbol, side=sl_side,
                order_type=OrderType.STOP_MARKET,
                stop_price=sl_price, quantity=fill.quantity,
                reduce_only=True, tag=f"sl_{int(time.time()*1000)}",
            ))
            if sl_order:
                state.sl_id = sl_order.order_id
                state.sl_price = sl_price
            else:
                log.warning("Initial SL placement failed for %s — emergency handler will take over", fill.symbol)
                state.sl_id = None
                state.sl_price = sl_price

        # Initialize trailing (no-op for binance_native mode)
        self._trailing.initialize(fill.symbol, fill.price, fill.side)

        # Place TP (independent of trailing mode)
        if self._cfg.stops.tp_pips > 0:
            if self._cfg.stops.use_pct_pips:
                tp_distance = fill.price * (self._cfg.stops.tp_pips / 100.0)
            else:
                tp_distance = self._cfg.stops.tp_pips

            if fill.side == OrderSide.BUY:
                tp_price = fill.price + tp_distance
            else:
                tp_price = fill.price - tp_distance

            tp_price = self._registry.round_price(fill.symbol, tp_price)
            tp_order = await self._safe_place_order(OrderIntent(
                symbol=fill.symbol, side=sl_side,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                stop_price=tp_price, quantity=fill.quantity,
                reduce_only=True, tag=f"tp_{int(time.time()*1000)}",
            ))
            if tp_order:
                state.tp_id = tp_order.order_id
                state.tp_price = tp_price

        # Persist and emit event
        await self._persist_state(fill.symbol)
        await self._bus.publish(PositionOpened(
            symbol=fill.symbol, side=fill.side.value,
            entry_price=fill.price, quantity=fill.quantity,
            timestamp_ms=fill.timestamp_ms,
        ))

    async def _handle_exit_fill(self, state: SymbolExecutionState, fill: Fill) -> None:
        """Position closed — calculate PnL, record trade, start cooldown."""
        # Determine exit reason
        if fill.order_id == state.sl_id or fill.tag.startswith(("sl_", "tsl_", "trailing_sl_", "native_tsl_")):
            # Check if this was the trailing stop (not the emergency SL)
            is_trailing = fill.order_id == state.tsl_id or self._trailing.is_active(fill.symbol) or fill.tag.startswith("native_tsl_")
            exit_reason = ExitReason.TRAILING_STOP if is_trailing else ExitReason.STOP_LOSS
        elif fill.order_id == state.tsl_id:
            exit_reason = ExitReason.TRAILING_STOP
        elif fill.order_id == state.tp_id or fill.tag.startswith("tp_"):
            exit_reason = ExitReason.TAKE_PROFIT
        elif fill.tag.startswith("reversal_close_only_"):
            exit_reason = ExitReason.REVERSAL
        else:
            exit_reason = ExitReason.MANUAL_CLOSE

        # Calculate PnL
        if state.position_state == PositionState.LONG:
            pnl = (fill.price - state.entry_price) * state.position_qty
        else:
            pnl = (state.entry_price - fill.price) * state.position_qty

        total_fees = state.entry_fee + fill.fee
        net_pnl = pnl - total_fees - state.accumulated_funding

        log.info(
            "EXIT FILL: %s %s @ %.8g pnl=%.4f fees=%.4f funding=%.4f net=%.4f reason=%s",
            fill.symbol, fill.side.value, fill.price, pnl, total_fees,
            state.accumulated_funding, net_pnl, exit_reason.value,
        )

        # Record trade
        trade = TradeRecord(
            symbol=fill.symbol,
            side=state.position_state.value,
            entry_price=state.entry_price,
            exit_price=fill.price,
            quantity=state.position_qty,
            realized_pnl=net_pnl,
            fees=total_fees,
            funding_cost=state.accumulated_funding,
            entry_time_ms=state.entry_time_ms,
            exit_time_ms=fill.timestamp_ms,
            exit_reason=exit_reason.value,
        )
        await self._repo.insert_trade(trade)

        # Cancel remaining orders (SL or TP whichever didn't fill)
        for order_id in [state.sl_id, state.tsl_id, state.tp_id]:
            if order_id and order_id != fill.order_id:
                await self._safe_cancel(fill.symbol, order_id)

        # Cancel any pending reversal order
        if state.pending_reversal_id:
            await self._safe_cancel(fill.symbol, state.pending_reversal_id)

        # Cancel any remaining entry orders (opposite side from hedge mode, etc.)
        for entry_id in [state.entry_buy_id, state.entry_sell_id]:
            if entry_id:
                await self._safe_cancel(fill.symbol, entry_id)

        # Emit event
        await self._bus.publish(PositionClosed(
            symbol=fill.symbol,
            side=state.position_state.value,
            entry_price=state.entry_price,
            exit_price=fill.price,
            realized_pnl=net_pnl,
            exit_reason=exit_reason.value,
            timestamp_ms=fill.timestamp_ms,
        ))

        # Reset ALL state + start cooldown
        self._trailing.clear(fill.symbol)
        state.position_state = PositionState.FLAT
        state.position_qty = 0.0
        state.entry_price = 0.0
        state.entry_time_ms = 0
        state.entry_fee = 0.0
        state.sl_id = None
        state.sl_price = None
        state.tsl_id = None
        state.tp_id = None
        state.tp_price = None
        state.entry_buy_id = None
        state.entry_buy_stop_price = None
        state.entry_sell_id = None
        state.entry_sell_stop_price = None
        state.trailing_watermark = 0.0
        state.pending_reversal_id = None
        state.accumulated_funding = 0.0
        state.cooldown_remaining = self._cfg.strategy.cooldown_candles

        await self._persist_state(fill.symbol)

    async def _handle_opposite_order(self, state: SymbolExecutionState, fill: Fill) -> None:
        """Handle the opposite pending entry order based on config."""
        mode = self._cfg.reversed_order.mode
        opposite_id = state.entry_sell_id if fill.side == OrderSide.BUY else state.entry_buy_id

        if not opposite_id:
            return

        if mode == "cancel":
            await self._safe_cancel(fill.symbol, opposite_id)
            if fill.side == OrderSide.BUY:
                state.entry_sell_id = None
                state.entry_sell_stop_price = None
            else:
                state.entry_buy_id = None
                state.entry_buy_stop_price = None

        elif mode == "keep_close_only":
            # Cancel and re-place as reduce_only
            opposite_order = None
            orders = await self._adapter.get_open_orders(fill.symbol)
            for o in orders:
                if o.order_id == opposite_id:
                    opposite_order = o
                    break

            await self._safe_cancel(fill.symbol, opposite_id)
            if opposite_order and opposite_order.stop_price:
                new_order = await self._adapter.place_order(OrderIntent(
                    symbol=fill.symbol,
                    side=opposite_order.side,
                    order_type=opposite_order.order_type,
                    stop_price=opposite_order.stop_price,
                    quantity=fill.quantity,
                    reduce_only=True,
                    tag=f"reversal_close_only_{int(time.time()*1000)}",
                ))
                state.pending_reversal_id = new_order.order_id

        elif mode == "keep_reverse":
            # Keep as-is — will reverse position on fill
            state.pending_reversal_id = opposite_id

        # "hedge" mode: keep both sides open (requires hedge mode on exchange)

    # ─── Trailing Stop ───────────────────────────────────

    async def on_tick(self, symbol: str, current_price: float) -> None:
        """Called on every price tick — manage trailing stop.

        Throttled to max 1 update per second per symbol to prevent
        DB connection pool exhaustion from high-frequency bookTicker events.
        """
        state = self.get_state(symbol)
        if not state.has_position or not self._cfg.trailing.enabled:
            return

        # Binance native trailing is handled server-side — no custom logic needed
        if self._cfg.trailing.mode == "binance_native":
            return

        # EMERGENCY: If sl_id is None but we have a position, the SL was lost
        # (failed trailing placement). Re-place it immediately, no throttle.
        if state.sl_id is None and state.sl_price is not None:
            lock = self._tick_locks.setdefault(symbol, asyncio.Lock())
            if lock.locked():
                return
            async with lock:
                sl_side = OrderSide.SELL if state.position_state == PositionState.LONG else OrderSide.BUY
                sl_order = await self._safe_place_order(OrderIntent(
                    symbol=symbol, side=sl_side,
                    order_type=OrderType.STOP_MARKET,
                    stop_price=state.sl_price, quantity=state.position_qty,
                    reduce_only=True, tag=f"emergency_sl_{int(time.time()*1000)}",
                ))
                if sl_order:
                    state.sl_id = sl_order.order_id
                    await self._persist_state(symbol)
                    log.info("EMERGENCY SL restored: %s @ %.8g", symbol, state.sl_price)
                else:
                    # SL price is already breached (price moved past it).
                    # Close position at market immediately — we're beyond our risk limit.
                    log.warning(
                        "SL BREACHED: %s SL=%.8g already past current price — closing at MARKET",
                        symbol, state.sl_price,
                    )
                    close_order = await self._safe_place_order(OrderIntent(
                        symbol=symbol, side=sl_side,
                        order_type=OrderType.MARKET,
                        stop_price=None, quantity=state.position_qty,
                        reduce_only=True, tag=f"sl_breach_close_{int(time.time()*1000)}",
                    ))
                    if close_order:
                        log.info("SL BREACH: Market close sent for %s", symbol)
                return  # Don't proceed with trailing logic until SL is restored

        # Throttle: max 1 trailing update per second per symbol
        now = time.monotonic()
        last = self._last_tick_time.get(symbol, 0)
        if now - last < 1.0:
            return
        self._last_tick_time[symbol] = now

        # Per-symbol lock to prevent concurrent trailing SL placements
        lock = self._tick_locks.setdefault(symbol, asyncio.Lock())
        if lock.locked():
            return  # previous tick still processing, skip
        async with lock:
            new_sl = self._trailing.update(
                symbol=symbol,
                current_price=current_price,
                entry_price=state.entry_price,
                current_sl_price=state.sl_price or 0,
                position_side=state.position_side,
                state=state,
            )

            if new_sl:
                # Round BEFORE comparing to avoid floating-point thrashing
                new_sl = self._registry.round_price(symbol, new_sl)

                if new_sl == state.sl_price:
                    return  # No actual change after rounding

                # ── BREACH CHECK: Is the new SL already past the current price? ──
                # LONG → SL is SELL STOP → breached if current_price <= new_sl
                # SHORT → SL is BUY STOP → breached if current_price >= new_sl
                sl_breached = False
                if state.position_state == PositionState.LONG and current_price <= new_sl:
                    sl_breached = True
                elif state.position_state == PositionState.SHORT and current_price >= new_sl:
                    sl_breached = True

                if sl_breached:
                    # Price has already moved past the trailing SL level.
                    # Do NOT cancel the old SL — close at market immediately.
                    log.warning(
                        "TRAILING SL BREACHED: %s new_sl=%.8g but current=%.8g — closing at MARKET",
                        symbol, new_sl, current_price,
                    )
                    sl_side = OrderSide.SELL if state.position_state == PositionState.LONG else OrderSide.BUY
                    # Cancel the existing SL first (it's wider than new_sl, might not trigger)
                    if state.sl_id:
                        await self._safe_cancel(symbol, state.sl_id)
                        state.sl_id = None
                    close_order = await self._safe_place_order(OrderIntent(
                        symbol=symbol, side=sl_side,
                        order_type=OrderType.MARKET,
                        stop_price=None, quantity=state.position_qty,
                        reduce_only=True, tag=f"trailing_breach_close_{int(time.time()*1000)}",
                    ))
                    if close_order:
                        log.info("TRAILING BREACH: Market close sent for %s", symbol)
                    return

                # CRITICAL: Cancel old SL first. If cancel fails, do NOT place
                # a new one — that would stack duplicate SL orders on the exchange.
                if state.sl_id:
                    cancelled = await self._safe_cancel(symbol, state.sl_id)
                    if not cancelled:
                        log.warning(
                            "Trailing SL skip: failed to cancel old SL %s for %s — not placing new one",
                            state.sl_id, symbol,
                        )
                        return

                sl_side = OrderSide.SELL if state.position_state == PositionState.LONG else OrderSide.BUY
                sl_order = await self._safe_place_order(OrderIntent(
                    symbol=symbol, side=sl_side,
                    order_type=OrderType.STOP_MARKET,
                    stop_price=new_sl, quantity=state.position_qty,
                    reduce_only=True, tag=f"trailing_sl_{int(time.time()*1000)}",
                ))
                if sl_order:
                    state.sl_id = sl_order.order_id
                    state.sl_price = new_sl  # update cache
                    await self._persist_state(symbol)
                    log.info("Trailing SL moved: %s → %.8g", symbol, new_sl)
                    from dashrock.core.events import TrailingMoved
                    await self._bus.publish(TrailingMoved(symbol=symbol, new_sl=new_sl))
                else:
                    # New SL placement failed unexpectedly.
                    # We already cancelled the old SL, position is unprotected.
                    log.warning(
                        "DANGER: Trailing SL placement failed for %s — closing at MARKET as safety.",
                        symbol,
                    )
                    close_order = await self._safe_place_order(OrderIntent(
                        symbol=symbol, side=sl_side,
                        order_type=OrderType.MARKET,
                        stop_price=None, quantity=state.position_qty,
                        reduce_only=True, tag=f"trailing_fail_close_{int(time.time()*1000)}",
                    ))
                    if close_order:
                        log.info("TRAILING FAIL: Market close sent for %s", symbol)
                    state.sl_id = None

    # ─── Helpers ─────────────────────────────────────────

    async def _safe_place_order(self, intent: OrderIntent) -> LiveOrder | None:
        """Place an order safely, returning None if the adapter raises an error."""
        try:
            order = await self._adapter.place_order(intent)
            await self._bus.publish(OrderPlaced(order=order))
            return order
        except Exception as e:
            log.error("Failed to place order for %s: %s", intent.symbol, e)
            return None

    async def _safe_cancel(self, symbol: str, order_id: str) -> bool:
        """Cancel an order. Returns True if confirmed gone, False if might still be live.

        Distinguishes between:
        - OrderNotFoundError: already cancelled/filled → harmless, return True
        - Other exceptions: might be orphaned on exchange → return False
        """
        try:
            await self._adapter.cancel_order(symbol, order_id)
            await self._repo.update_order_status(order_id, "CANCELED")
            await self._bus.publish(OrderCancelled(order_id=order_id, symbol=symbol))
            return True
        except OrderNotFoundError:
            # Already cancelled or filled on the exchange — harmless
            log.debug("Order %s already gone on exchange", order_id)
            await self._repo.update_order_status(order_id, "CANCELED")
            return True
        except Exception:
            log.error(
                "CRITICAL: Failed to cancel order %s on %s — may be orphaned!",
                order_id, symbol, exc_info=True,
            )
            return False
