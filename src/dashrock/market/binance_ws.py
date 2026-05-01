"""Binance Futures public WebSocket client — no API key required.

Connects to the appropriate WebSocket endpoint based on mode:
- live:    fstream.binance.com  (production)
- testnet: stream.binancefuture.com  (testnet)
- paper:   fstream.binance.com  (uses live data for paper trading)

IMPORTANT: Binance routes streams to different endpoints:
- /market  — kline, markPrice, aggTrade (regular market data)
- /public  — depth, bookTicker (high-frequency public data)
- /private — user data (listenKey)
Connections without a route only receive /public data.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets

log = logging.getLogger(__name__)

# Live production endpoints (routed)
BINANCE_FUTURES_MARKET = "wss://fstream.binance.com/market/stream"
BINANCE_FUTURES_PUBLIC = "wss://fstream.binance.com/public/stream"
# Testnet (no routing needed — testnet doesn't enforce routes)
BINANCE_TESTNET_WS = "wss://stream.binancefuture.com/stream"


class BinanceStream:
    """Single WebSocket connection for one symbol's combined streams.

    For live mode, creates two connections:
    - /market for kline data
    - /public for bookTicker data
    For testnet, uses a single unrouted connection (testnet doesn't enforce routes).
    """

    def __init__(self, symbol: str, timeframe: str, market_url: str, public_url: str | None = None) -> None:
        self._symbol = symbol.lower()
        self._timeframe = timeframe
        self._market_url = market_url
        self._public_url = public_url  # None for testnet (single connection)
        self._ws_market: Any = None
        self._ws_public: Any = None
        self._connected = asyncio.Event()
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    async def connect(self) -> None:
        kline_stream = f"{self._symbol}@kline_{self._timeframe}"
        book_stream = f"{self._symbol}@bookTicker"

        if self._public_url:
            # Live mode: two separate connections for different routes
            market_url = f"{self._market_url}?streams={kline_stream}"
            public_url = f"{self._public_url}?streams={book_stream}"
            log.info("Connecting to Binance WS (routed): %s → /market, %s → /public", kline_stream, book_stream)
            self._ws_market = await websockets.connect(market_url, ping_interval=30, ping_timeout=20, open_timeout=30)
            self._ws_public = await websockets.connect(public_url, ping_interval=30, ping_timeout=20, open_timeout=30)
            # Start reader tasks that feed into a single queue
            self._tasks = [
                asyncio.create_task(self._reader(self._ws_market, "market")),
                asyncio.create_task(self._reader(self._ws_public, "public")),
            ]
        else:
            # Testnet: single unrouted connection
            streams = f"{kline_stream}/{book_stream}"
            url = f"{self._market_url}?streams={streams}"
            log.info("Connecting to Binance WS (testnet): %s", streams)
            self._ws_market = await websockets.connect(url, ping_interval=30, ping_timeout=20, open_timeout=30)
            self._tasks = [
                asyncio.create_task(self._reader(self._ws_market, "testnet")),
            ]
        self._connected.set()

    async def _reader(self, ws: Any, label: str) -> None:
        """Read from a WebSocket and push messages into the shared queue."""
        try:
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                # Combined stream format: {"stream": "...", "data": {...}}
                await self._queue.put(msg)
        except (websockets.ConnectionClosed, ConnectionError):
            log.warning("Binance WS %s disconnected for %s", label, self._symbol)
        except asyncio.CancelledError:
            return

    async def recv(self) -> dict:
        if not self._connected.is_set():
            await self.connect()
        try:
            return await self._queue.get()
        except Exception:
            log.warning("Binance WS queue error for %s, reconnecting...", self._symbol)
            await self.close()
            await asyncio.sleep(1)
            await self.connect()
            return await self._queue.get()

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        for ws in [self._ws_market, self._ws_public]:
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass
        self._ws_market = None
        self._ws_public = None
        self._connected.clear()


def create_binance_ws_factory(timeframe: str = "1m", mode: str = "live"):
    """Return a factory function compatible with MarketDataService.ws_factory.

    Args:
        timeframe: Kline timeframe (e.g. "1m", "5m").
        mode: Trading mode — "testnet" uses the testnet WS endpoint.

    Usage:
        md = MarketDataService(
            ...,
            ws_factory=create_binance_ws_factory("1m", mode="testnet"),
        )
    """
    if mode == "testnet":
        market_url = BINANCE_TESTNET_WS
        public_url = None  # single connection for testnet
    else:
        market_url = BINANCE_FUTURES_MARKET
        public_url = BINANCE_FUTURES_PUBLIC

    log.info("WS factory created: timeframe=%s mode=%s market=%s public=%s",
             timeframe, mode, market_url, public_url or "same")

    def factory(symbol: str, stream_type: str) -> BinanceStream:
        return BinanceStream(symbol, timeframe, market_url, public_url)
    return factory

