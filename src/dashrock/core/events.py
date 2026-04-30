"""Event bus — typed pub/sub with backpressure awareness.

All internal communication between components goes through this bus.
Handlers are awaited in order (not fire-and-forget) to ensure backpressure.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from dashrock.core.types import BookTop, Candle, Fill, LiveOrder

log = logging.getLogger(__name__)

E = TypeVar("E")
Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    """Typed async event bus with ordered handler execution."""

    def __init__(self) -> None:
        self._subs: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> None:
        self._subs[event_type].append(handler)  # type: ignore[arg-type]

    async def publish(self, event: Any) -> None:
        """Publish an event. Handlers are awaited sequentially (backpressure)."""
        handlers = list(self._subs.get(type(event), ()))
        for h in handlers:
            try:
                await h(event)
            except Exception:
                log.exception("Event handler failed for %s: %s", type(event).__name__, h)

    def publish_nowait(self, event: Any) -> None:
        """Publish an event without awaiting handlers (fire-and-forget).
        
        Use for heavy events (CandleClosed) to avoid blocking the data stream.
        """
        handlers = list(self._subs.get(type(event), ()))
        for h in handlers:
            asyncio.create_task(self._safe_call(h, event, type(event).__name__))

    @staticmethod
    async def _safe_call(handler: Handler, event: Any, name: str) -> None:
        try:
            await handler(event)
        except Exception:
            log.exception("Event handler failed for %s: %s", name, handler)


# ─── Event Payloads ─────────────────────────────────────────────


@dataclass(frozen=True)
class CandleClosed:
    candle: Candle


@dataclass(frozen=True)
class CandleUpdated:
    """Forming (not yet closed) candle update."""
    candle: Candle


@dataclass(frozen=True)
class TickUpdate:
    book: BookTop


@dataclass(frozen=True)
class SpreadUpdate:
    symbol: str
    spread: float


@dataclass(frozen=True)
class OrderPlaced:
    order: LiveOrder


@dataclass(frozen=True)
class OrderCancelled:
    order_id: str
    symbol: str


@dataclass(frozen=True)
class TrailingMoved:
    symbol: str
    new_sl: float


@dataclass(frozen=True)
class NativeTrailingPlaced:
    symbol: str
    callback_rate: float
    activate_price: float | None
    order_id: str


@dataclass(frozen=True)
class FillEvent:
    fill: Fill


@dataclass(frozen=True)
class PositionOpened:
    symbol: str
    side: str
    entry_price: float
    quantity: float
    timestamp_ms: int


@dataclass(frozen=True)
class PositionClosed:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    realized_pnl: float
    exit_reason: str
    timestamp_ms: int


@dataclass(frozen=True)
class EquityUpdate:
    equity_usd: float
    timestamp_ms: int


@dataclass(frozen=True)
class LogEvent:
    level: str
    message: str
    timestamp_ms: int


@dataclass(frozen=True)
class ScannerUpdate:
    rankings: list[dict]
    timestamp_ms: int


@dataclass(frozen=True)
class SafetyTriggered:
    reason: str
    timestamp_ms: int


@dataclass(frozen=True)
class StateChanged:
    """Engine state machine transition."""
    old_state: str
    new_state: str
    reason: str
    timestamp_ms: int


@dataclass(frozen=True)
class FundingRateUpdate:
    """New funding rate received for a symbol."""
    symbol: str
    rate: float
    next_funding_time_ms: int
    timestamp_ms: int
