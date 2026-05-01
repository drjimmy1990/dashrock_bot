"""Binance Futures public WebSocket client — no API key required.

Connects to the appropriate WebSocket endpoint based on mode:
- live:    fstream.binance.com  (production)
- testnet: stream.binancefuture.com  (testnet — some symbols lack kline data on live)
- paper:   fstream.binance.com  (uses live data for paper trading)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets

log = logging.getLogger(__name__)

BINANCE_FUTURES_WS = "wss://fstream.binance.com/stream"
BINANCE_TESTNET_WS = "wss://stream.binancefuture.com/stream"


class BinanceStream:
    """Single WebSocket connection for one symbol's combined streams."""

    def __init__(self, symbol: str, timeframe: str, base_url: str = BINANCE_FUTURES_WS) -> None:
        self._symbol = symbol.lower()
        self._timeframe = timeframe
        self._base_url = base_url
        self._ws: Any = None
        self._connected = asyncio.Event()

    async def connect(self) -> None:
        streams = f"{self._symbol}@kline_{self._timeframe}/{self._symbol}@bookTicker"
        url = f"{self._base_url}?streams={streams}"
        log.info("Connecting to Binance WS: %s (base=%s)", streams, self._base_url.split("//")[1].split("/")[0])
        self._ws = await websockets.connect(url, ping_interval=30, ping_timeout=20, open_timeout=30)
        self._connected.set()

    async def recv(self) -> dict:
        if self._ws is None:
            await self.connect()
        try:
            raw = await self._ws.recv()
            return json.loads(raw)
        except (websockets.ConnectionClosed, ConnectionError):
            log.warning("Binance WS disconnected for %s, reconnecting...", self._symbol)
            self._connected.clear()
            await asyncio.sleep(1)
            await self.connect()
            raw = await self._ws.recv()
            return json.loads(raw)

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()


def create_binance_ws_factory(timeframe: str = "1m", mode: str = "live"):
    """Return a factory function compatible with MarketDataService.ws_factory.

    Args:
        timeframe: Kline timeframe (e.g. "1m", "5m").
        mode: Trading mode — "testnet" uses the testnet WS endpoint
              (critical for symbols like XAGUSDT that don't stream klines on live).

    Usage:
        md = MarketDataService(
            ...,
            ws_factory=create_binance_ws_factory("1m", mode="testnet"),
        )
    """
    base_url = BINANCE_TESTNET_WS if mode == "testnet" else BINANCE_FUTURES_WS
    log.info("WS factory created: timeframe=%s mode=%s base=%s", timeframe, mode, base_url)

    def factory(symbol: str, stream_type: str) -> BinanceStream:
        return BinanceStream(symbol, timeframe, base_url)
    return factory
