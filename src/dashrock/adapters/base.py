"""Execution adapter interface — all exchange connectors must implement this.

Expanded from v1 with: batch order support, rate limit info, funding rates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from dashrock.core.types import Fill, LiveOrder, OrderIntent, Position

FillCallback = Callable[[Fill], Awaitable[None]]


# ─── Custom Exceptions ──────────────────────────────────────────

class OrderNotFoundError(Exception):
    """Order was already cancelled or filled on the exchange."""


class InsufficientMarginError(Exception):
    """Not enough margin to place this order."""


class RateLimitError(Exception):
    """Exchange rate limit hit — retry after delay."""


class ExchangeError(Exception):
    """Generic exchange error with code and message."""

    def __init__(self, code: int, msg: str) -> None:
        self.code = code
        self.msg = msg
        super().__init__(f"Binance error {code}: {msg}")


class ExecutionAdapter(ABC):
    """Interface for exchange execution (live, testnet, simulator)."""

    @abstractmethod
    async def start(self) -> None:
        """Connect and begin listening for fills."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect and cleanup."""
        ...

    @abstractmethod
    async def place_order(self, intent: OrderIntent) -> LiveOrder:
        """Place an order and return the exchange-assigned order."""
        ...

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> None:
        """Cancel an open order. No-op if already filled/cancelled."""
        ...

    @abstractmethod
    async def get_open_orders(self, symbol: str) -> list[LiveOrder]:
        """Return all currently open orders for a symbol."""
        ...

    @abstractmethod
    async def get_all_open_orders(self) -> list[LiveOrder]:
        """Return all currently open orders across all symbols."""
        ...

    @abstractmethod
    async def get_position(self, symbol: str) -> Position:
        """Return the current position for a symbol."""
        ...

    @abstractmethod
    async def get_equity_usd(self) -> float:
        """Return the total account equity in USD."""
        ...

    @abstractmethod
    def set_fill_handler(self, handler: FillCallback) -> None:
        """Register the callback invoked on every fill."""
        ...

    # ─── Optional — override for enhanced functionality ──

    async def get_funding_rate(self, symbol: str) -> float:
        """Return the current funding rate for a symbol. Default: 0."""
        return 0.0

    async def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all open orders for a symbol. Returns count cancelled.

        Default implementation calls cancel_order() for each.
        Override with a batch API call for efficiency.
        """
        orders = await self.get_open_orders(symbol)
        for o in orders:
            await self.cancel_order(symbol, o.order_id)
        return len(orders)
