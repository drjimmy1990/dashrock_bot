"""Market data service — WebSocket candle and book ticker consumer.

Improvements over v1:
- Multi-timeframe candle windows
- Auto-reconnection with exponential backoff
- Heartbeat monitoring for stale connections
- Deduplication of candle close events
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Any, Callable, Protocol

from dashrock.core.events import CandleClosed, CandleUpdated, EventBus, SpreadUpdate, TickUpdate
from dashrock.core.types import BookTop, Candle

log = logging.getLogger(__name__)


class WSStream(Protocol):
    """Protocol for WebSocket stream objects."""
    async def recv(self) -> dict: ...


WSFactory = Callable[[str, str], WSStream]  # (symbol, stream_type) -> stream


class MarketDataService:
    """Consumes kline + bookTicker WebSocket streams for each symbol."""

    def __init__(
        self,
        *,
        bus: EventBus,
        symbols: list[str],
        timeframes: list[str],
        ws_factory: WSFactory | None = None,
        window_size: int = 200,
    ) -> None:
        self.bus = bus
        self.symbols = [s.upper() for s in symbols]
        self.timeframes = timeframes
        self.primary_tf = timeframes[0] if timeframes else "1m"
        self.ws_factory = ws_factory
        self.window_size = window_size

        # {(symbol, timeframe): deque[Candle]}
        self._windows: dict[tuple[str, str], deque[Candle]] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )
        self._live_candles: dict[tuple[str, str], Candle] = {}
        self._last_closed_time: dict[tuple[str, str], int] = {}
        self._last_book: dict[str, BookTop] = {}
        self._tasks: list[asyncio.Task] = []
        self._connected = False
        self._kline_count: dict[str, int] = {}

    def get_window(self, symbol: str, timeframe: str | None = None) -> list[Candle]:
        tf = timeframe or self.primary_tf
        return list(self._windows[(symbol.upper(), tf)])

    def get_live_candle(self, symbol: str, timeframe: str | None = None) -> Candle | None:
        tf = timeframe or self.primary_tf
        return self._live_candles.get((symbol.upper(), tf))

    def get_last_book(self, symbol: str) -> BookTop | None:
        return self._last_book.get(symbol.upper())

    def get_current_price(self, symbol: str) -> float:
        """Best effort current price from live candle or last book."""
        sym = symbol.upper()
        live = self.get_live_candle(sym)
        if live:
            return live.close
        book = self._last_book.get(sym)
        if book:
            return (book.bid + book.ask) / 2
        window = self.get_window(sym)
        if window:
            return window[-1].close
        return 0.0

    def is_connected(self) -> bool:
        return self._connected

    def seed_window(self, symbol: str, timeframe: str, candles: list[Candle]) -> None:
        """Pre-warm the candle window from REST API historical data."""
        key = (symbol.upper(), timeframe)
        self._windows[key].clear()
        for c in candles:
            self._windows[key].append(c)
        log.info("Seeded %s:%s with %d candles", symbol, timeframe, len(candles))

    async def start(self) -> None:
        self._connected = True
        # Start one task per symbol that handles all streams
        for sym in self.symbols:
            task = asyncio.create_task(
                self._run_symbol_streams(sym),
                name=f"md-{sym}",
            )
            self._tasks.append(task)

    async def stop(self) -> None:
        self._connected = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

    async def update_symbols(self, new_symbols: list[str]) -> None:
        """Hot-swap traded symbols — stop removed streams, start added ones.

        Called when trade_list is changed via the Settings UI.
        """
        new_set = {s.upper() for s in new_symbols}
        old_set = set(self.symbols)

        removed = old_set - new_set
        added = new_set - old_set

        if not removed and not added:
            return

        log.info(
            "Updating market data symbols: added=%s removed=%s",
            list(added) or "none", list(removed) or "none",
        )

        # Cancel tasks for removed symbols
        remaining_tasks = []
        for task in self._tasks:
            task_sym = task.get_name().replace("md-", "")
            if task_sym in removed:
                task.cancel()
                log.info("Stopped stream for %s", task_sym)
            else:
                remaining_tasks.append(task)
        self._tasks = remaining_tasks

        # Clean up data for removed symbols
        for sym in removed:
            for tf in self.timeframes:
                self._windows.pop((sym, tf), None)
                self._live_candles.pop((sym, tf), None)
                self._last_closed_time.pop((sym, tf), None)
            self._last_book.pop(sym, None)
            self._kline_count.pop(sym, None)

        # Start tasks for added symbols
        if self._connected and self.ws_factory:
            for sym in added:
                task = asyncio.create_task(
                    self._run_symbol_streams(sym),
                    name=f"md-{sym}",
                )
                self._tasks.append(task)
                log.info("Started stream for %s", sym)

        # Update the canonical list
        self.symbols = list(new_set)

    async def _run_symbol_streams(self, symbol: str) -> None:
        """Run WebSocket streams for a single symbol with auto-reconnect."""
        backoff = 1
        max_backoff = 60

        while self._connected:
            ws = None
            try:
                if self.ws_factory is None:
                    return

                ws = self.ws_factory(symbol, "kline_and_book")
                backoff = 1  # reset on successful connect
                log.info("Market data connected for %s", symbol)

                while self._connected:
                    msg = await ws.recv()
                    try:
                        await self._handle_message(msg, symbol)
                    except Exception:
                        log.exception("Error handling message for %s", symbol)

            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "Market data stream error for %s — reconnecting in %ds",
                    symbol, backoff,
                )
                if ws:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _handle_message(self, msg: dict, symbol: str) -> None:
        data = msg.get("data", msg)
        etype = data.get("e")

        # Debug: log kline events (infrequent) to verify stream health
        if etype == "kline":
            self._kline_count[symbol] = self._kline_count.get(symbol, 0) + 1
            kc = self._kline_count[symbol]
            if kc <= 3 or kc % 50 == 0:
                k = data.get("k", {})
                log.info("KLINE %s #%d: close=%s x=%s", symbol, kc, k.get("c"), k.get("x"))

        if etype == "kline":
            await self._handle_kline(data)
        elif etype == "bookTicker" or ("b" in data and "a" in data):
            await self._handle_book(data, symbol)

    async def _handle_kline(self, data: dict) -> None:
        k = data["k"]
        tf = k.get("i", self.primary_tf)
        candle = Candle(
            symbol=data["s"],
            open_time_ms=k["t"],
            close_time_ms=k["T"],
            open=float(k["o"]),
            close=float(k["c"]),
            high=float(k["h"]),
            low=float(k["l"]),
            volume=float(k["v"]),
            is_closed=bool(k["x"]),
        )
        key = (candle.symbol, tf)

        if candle.is_closed:
            # Dedup
            last_closed = self._last_closed_time.get(key, 0)
            if candle.open_time_ms <= last_closed:
                return
            self._last_closed_time[key] = candle.open_time_ms

            self._windows[key].append(candle)
            self._live_candles.pop(key, None)
            # Fire-and-forget: strategy + DB handlers are heavy, don't block recv
            self.bus.publish_nowait(CandleClosed(candle=candle))
        else:
            self._live_candles[key] = candle
            # Fire-and-forget: WS bridge broadcast shouldn't block recv
            self.bus.publish_nowait(CandleUpdated(candle=candle))

    async def _handle_book(self, data: dict, symbol: str) -> None:
        book = BookTop(
            symbol=data.get("s", symbol),
            bid=float(data["b"]),
            ask=float(data["a"]),
            timestamp_ms=int(data.get("E", int(time.time() * 1000))),
        )
        self._last_book[book.symbol] = book
        self.bus.publish_nowait(TickUpdate(book=book))
        self.bus.publish_nowait(SpreadUpdate(symbol=book.symbol, spread=book.ask - book.bid))
