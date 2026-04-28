"""Improved simulator adapter — in-memory matching engine.

Improvements over v1:
- Funding rate simulation (configurable 8h interval)
- Optional latency simulation
- Proper Candle import (fixes W-16)
- Atomic position tracking with signed quantities
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import random
import time
from dataclasses import replace

from dashrock.adapters.base import ExecutionAdapter, FillCallback
from dashrock.config import SimulatorCfg
from dashrock.core.types import (
    BookTop,
    Candle,
    Fill,
    LiveOrder,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

log = logging.getLogger(__name__)


class SimulatorAdapter(ExecutionAdapter):
    """In-memory matching engine driven by external BookTop / Candle ticks."""

    def __init__(self, cfg: SimulatorCfg) -> None:
        self.cfg = cfg
        # Use timestamp prefix to avoid duplicate key collisions across restarts
        self._id_prefix = f"sim-{int(time.time())}"
        self._id_gen = itertools.count(1)
        self._orders: dict[str, LiveOrder] = {}
        self._positions: dict[str, Position] = {}
        self._equity = cfg.starting_equity_usd
        self._fill_handler: FillCallback | None = None
        self._lock = asyncio.Lock()
        self._funding_task: asyncio.Task | None = None
        self._last_book: dict[str, BookTop] = {}  # cache for instant MARKET fills

    async def start(self) -> None:
        if self.cfg.simulate_funding:
            self._funding_task = asyncio.create_task(self._funding_loop())
        log.info(
            "Simulator started — equity=$%.2f, fee=%.4f%%, slippage=%.4f%%",
            self._equity, self.cfg.taker_fee_pct, self.cfg.slippage_noise_pips,
        )

    async def stop(self) -> None:
        if self._funding_task:
            self._funding_task.cancel()
            self._funding_task = None

    def set_fill_handler(self, handler: FillCallback) -> None:
        self._fill_handler = handler

    async def place_order(self, intent: OrderIntent) -> LiveOrder:
        async with self._lock:
            order_id = f"{self._id_prefix}-{next(self._id_gen)}"
            order = LiveOrder(
                order_id=order_id,
                symbol=intent.symbol,
                side=intent.side,
                order_type=intent.order_type,
                stop_price=intent.stop_price,
                quantity=intent.quantity,
                status=OrderStatus.NEW,
                reduce_only=intent.reduce_only,
                tag=intent.tag,
            )

            # MARKET orders fill immediately — don't wait for the next tick.
            # This is critical for close-all which pauses the engine right after.
            if intent.order_type == OrderType.MARKET:
                last_book = self._last_book.get(intent.symbol)
                if last_book:
                    price = last_book.ask if intent.side == OrderSide.BUY else last_book.bid
                else:
                    # Fallback: use position entry price (better than nothing)
                    pos = self._positions.get(intent.symbol)
                    price = pos.entry_price if pos and pos.entry_price > 0 else 0
                if price > 0:
                    ts_ms = int(time.time() * 1000)
                    fill = self._create_fill(order, price, ts_ms)
                    self._apply_fill_to_position(order, fill.price, ts_ms)
                    order.status = OrderStatus.FILLED
                    # Emit fill outside the lock to avoid deadlock
                    if self._fill_handler:
                        asyncio.create_task(self._fill_handler(fill))
                    return order

            self._orders[order_id] = order
            return order

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        async with self._lock:
            order = self._orders.get(order_id)
            if order and order.symbol == symbol and order.status == OrderStatus.NEW:
                order.status = OrderStatus.CANCELED
                del self._orders[order_id]

    async def cancel_all_orders(self, symbol: str) -> int:
        async with self._lock:
            to_cancel = [
                oid for oid, o in self._orders.items()
                if o.symbol == symbol and o.status == OrderStatus.NEW
            ]
            for oid in to_cancel:
                self._orders[oid].status = OrderStatus.CANCELED
                del self._orders[oid]
            return len(to_cancel)

    async def get_open_orders(self, symbol: str) -> list[LiveOrder]:
        async with self._lock:
            return [
                o for o in self._orders.values()
                if o.symbol == symbol and o.status == OrderStatus.NEW
            ]

    async def get_all_open_orders(self) -> list[LiveOrder]:
        async with self._lock:
            return [o for o in self._orders.values() if o.status == OrderStatus.NEW]

    async def get_position(self, symbol: str) -> Position:
        return self._positions.get(
            symbol,
            Position(symbol=symbol, side=None, quantity=0, entry_price=0, opened_at_ms=0),
        )

    async def get_equity_usd(self) -> float:
        return self._equity

    async def get_funding_rate(self, symbol: str) -> float:
        return self.cfg.funding_rate_pct / 100.0

    # ─── Tick processing ─────────────────────────────────

    async def on_book(self, book: BookTop) -> None:
        """Process a book update; trigger eligible stop orders."""
        self._last_book[book.symbol] = book  # cache for instant MARKET fills
        fills = await self._check_triggers(book.symbol, book=book)
        await self._emit_fills(fills)

    async def on_candle(self, candle: Candle) -> None:
        """Process a candle; trigger eligible stop orders."""
        fills = await self._check_triggers(candle.symbol, candle=candle)
        await self._emit_fills(fills)

    async def _check_triggers(
        self,
        symbol: str,
        book: BookTop | None = None,
        candle: Candle | None = None,
    ) -> list[Fill]:
        fills: list[Fill] = []
        async with self._lock:
            triggered_ids: list[str] = []
            for oid, o in list(self._orders.items()):
                if o.symbol != symbol or o.status != OrderStatus.NEW:
                    continue

                price = self._check_order_trigger(o, book, candle)
                if price is not None:
                    ts_ms = (book.timestamp_ms if book else candle.close_time_ms) if (book or candle) else int(time.time() * 1000)
                    fill = self._create_fill(o, price, ts_ms)
                    fills.append(fill)
                    self._apply_fill_to_position(o, fill.price, ts_ms)
                    triggered_ids.append(oid)

            for oid in triggered_ids:
                self._orders[oid].status = OrderStatus.FILLED

        return fills

    def _check_order_trigger(
        self,
        o: LiveOrder,
        book: BookTop | None,
        candle: Candle | None,
    ) -> float | None:
        """Check if an order should trigger. Returns fill price or None."""
        if o.order_type == OrderType.MARKET:
            if book:
                return book.ask if o.side == OrderSide.BUY else book.bid
            if candle:
                return candle.close
            return None

        if o.stop_price is None:
            return None

        if o.order_type == OrderType.STOP_MARKET:
            if book:
                if o.side == OrderSide.BUY and book.ask >= o.stop_price:
                    return book.ask
                if o.side == OrderSide.SELL and book.bid <= o.stop_price:
                    return book.bid
            if candle:
                if o.side == OrderSide.BUY and candle.high >= o.stop_price:
                    return o.stop_price
                if o.side == OrderSide.SELL and candle.low <= o.stop_price:
                    return o.stop_price

        elif o.order_type == OrderType.TAKE_PROFIT_MARKET:
            if book:
                if o.side == OrderSide.SELL and book.bid >= o.stop_price:
                    return book.bid
                if o.side == OrderSide.BUY and book.ask <= o.stop_price:
                    return book.ask
            if candle:
                if o.side == OrderSide.SELL and candle.high >= o.stop_price:
                    return o.stop_price
                if o.side == OrderSide.BUY and candle.low <= o.stop_price:
                    return o.stop_price

        return None

    def _create_fill(self, o: LiveOrder, price: float, ts_ms: int) -> Fill:
        # Apply slippage (always adverse)
        noise_pct = random.uniform(0, self.cfg.slippage_noise_pips / 100.0)
        if o.side == OrderSide.BUY:
            price = price * (1 + noise_pct)
        else:
            price = price * (1 - noise_pct)

        notional = price * o.quantity
        fee = notional * (self.cfg.taker_fee_pct / 100.0)
        return Fill(
            order_id=o.order_id, symbol=o.symbol, side=o.side,
            price=price, quantity=o.quantity, fee=fee, timestamp_ms=ts_ms,
        )

    def _apply_fill_to_position(self, o: LiveOrder, price: float, ts_ms: int) -> None:
        notional = price * o.quantity
        fee = notional * (self.cfg.taker_fee_pct / 100.0)
        self._equity -= fee

        pos = self._positions.get(o.symbol)
        signed = o.quantity if o.side == OrderSide.BUY else -o.quantity

        if pos is None or pos.side is None:
            new_side = OrderSide.BUY if signed > 0 else OrderSide.SELL
            self._positions[o.symbol] = Position(
                symbol=o.symbol, side=new_side, quantity=abs(signed),
                entry_price=price, opened_at_ms=ts_ms,
            )
            return

        current_signed = pos.quantity if pos.side == OrderSide.BUY else -pos.quantity
        net = current_signed + signed

        if net == 0:
            pnl = (price - pos.entry_price) * current_signed
            self._equity += pnl
            self._positions[o.symbol] = Position(
                symbol=o.symbol, side=None, quantity=0, entry_price=0, opened_at_ms=0,
            )
        elif (net > 0) == (current_signed > 0):
            total = pos.quantity + o.quantity
            avg = (pos.entry_price * pos.quantity + price * o.quantity) / total
            self._positions[o.symbol] = replace(pos, quantity=total, entry_price=avg)
        else:
            pnl = (price - pos.entry_price) * current_signed
            self._equity += pnl
            new_side = OrderSide.BUY if net > 0 else OrderSide.SELL
            self._positions[o.symbol] = Position(
                symbol=o.symbol, side=new_side, quantity=abs(net),
                entry_price=price, opened_at_ms=ts_ms,
            )

    async def _emit_fills(self, fills: list[Fill]) -> None:
        if not self._fill_handler or not fills:
            return
        for f in fills:
            if self.cfg.latency_ms > 0:
                await asyncio.sleep(self.cfg.latency_ms / 1000.0)
            await self._fill_handler(f)

    async def _funding_loop(self) -> None:
        """Simulate funding rate charges every simulated 8 hours."""
        interval = 8 * 3600  # 8 hours in seconds
        try:
            while True:
                await asyncio.sleep(interval)
                async with self._lock:
                    for symbol, pos in self._positions.items():
                        if pos.side is None or pos.quantity == 0:
                            continue
                        notional = pos.entry_price * pos.quantity
                        funding_cost = notional * (self.cfg.funding_rate_pct / 100.0)
                        # Longs pay when rate is positive, shorts receive
                        if pos.side == OrderSide.BUY:
                            self._equity -= funding_cost
                        else:
                            self._equity += funding_cost
                        log.debug(
                            "Funding: %s %s cost=$%.4f equity=$%.2f",
                            symbol, pos.side.value, funding_cost, self._equity,
                        )
        except asyncio.CancelledError:
            pass
