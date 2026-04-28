"""Binance Futures public WebSocket client — no API key required.

Connects to fstream.binance.com for kline + bookTicker streams.
Used in ALL modes (paper/testnet/live) to feed MarketDataService.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets

log = logging.getLogger(__name__)

BINANCE_FUTURES_WS = "wss://fstream.binance.com/stream"


class BinanceStream:
    """Single WebSocket connection for one symbol's combined streams."""

    def __init__(self, symbol: str, timeframe: str) -> None:
        self._symbol = symbol.lower()
        self._timeframe = timeframe
        self._ws: Any = None
        self._connected = asyncio.Event()

    async def connect(self) -> None:
        streams = f"{self._symbol}@kline_{self._timeframe}/{self._symbol}@bookTicker"
        url = f"{BINANCE_FUTURES_WS}?streams={streams}"
        log.info("Connecting to Binance WS: %s", streams)
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


def create_binance_ws_factory(timeframe: str = "1m"):
    """Return a factory function compatible with MarketDataService.ws_factory.

    Usage:
        md = MarketDataService(
            ...,
            ws_factory=create_binance_ws_factory("1m"),
        )
    """
    def factory(symbol: str, stream_type: str) -> BinanceStream:
        return BinanceStream(symbol, timeframe)
    return factory
