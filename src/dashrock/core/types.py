"""Core domain types for the Dashrock trading engine.

All value objects, enums, and data classes used across the system.
Frozen dataclasses for immutability where appropriate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ─── Enums ──────────────────────────────────────────────────────


class EngineMode(str, Enum):
    """Trading mode."""
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    NEW = "NEW"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"


class PositionState(str, Enum):
    """Whether the engine considers itself flat, long, or short on a symbol."""
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(str, Enum):
    """Why a position was closed."""
    STOP_LOSS = "sl"
    TAKE_PROFIT = "tp"
    TRAILING_STOP = "trailing_sl"
    MANUAL_CLOSE = "manual"
    SAFETY_KILL = "safety"
    REVERSAL = "reversal"
    TIME_FILTER = "time_filter"


# ─── Market Data ────────────────────────────────────────────────


@dataclass(frozen=True)
class Candle:
    """One OHLCV candle bar."""
    symbol: str
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


@dataclass(frozen=True)
class BookTop:
    """Best bid/ask from the order book."""
    symbol: str
    bid: float
    ask: float
    timestamp_ms: int


# ─── Orders ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrderIntent:
    """Strategy's description of a desired pending order. No ID yet."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    stop_price: float | None
    quantity: float
    reduce_only: bool = False
    tag: str = ""  # e.g. "entry_buy_stop", "sl", "tp"
    callback_rate: float | None = None      # For TRAILING_STOP_MARKET (0.1-10 %)
    activate_price: float | None = None     # For TRAILING_STOP_MARKET activation


@dataclass
class LiveOrder:
    """An order known to the exchange (or simulator)."""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    stop_price: float | None
    quantity: float
    status: OrderStatus
    reduce_only: bool
    tag: str


# ─── Position ───────────────────────────────────────────────────


@dataclass
class Position:
    """Represents an open position on a symbol."""
    symbol: str
    side: OrderSide | None  # None when flat
    quantity: float  # always >= 0; direction is from `side`
    entry_price: float
    opened_at_ms: int


# ─── Fill ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Fill:
    """Notification that an order was filled."""
    order_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    fee: float
    timestamp_ms: int
    tag: str = ""


# ─── Strategy Output ────────────────────────────────────────────


@dataclass
class DesiredOrders:
    """Strategy output for one symbol: what entry orders we want alive."""
    symbol: str
    buy_stop: OrderIntent | None
    sell_stop: OrderIntent | None
    reference_price: float = 0.0  # Trigger candle close, for stale breakout guard


# ─── Trade Record ───────────────────────────────────────────────


@dataclass
class TradeRecord:
    """A completed (closed) trade — persisted to DB."""
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    realized_pnl: float
    fees: float
    entry_time_ms: int
    exit_time_ms: int
    exit_reason: str
    funding_cost: float = 0.0  # total funding paid/received during position
    id: int | None = None


# ─── Execution State ────────────────────────────────────────────


@dataclass
class SymbolExecutionState:
    """Per-symbol state tracked by the execution manager.

    Persisted to DB on every change so we survive crashes.
    """
    symbol: str
    position_state: PositionState = PositionState.FLAT
    entry_buy_id: str | None = None
    entry_buy_stop_price: float | None = None
    entry_sell_id: str | None = None
    entry_sell_stop_price: float | None = None
    sl_id: str | None = None
    sl_price: float | None = None  # cached — no more N+1 queries!
    tsl_id: str | None = None  # native trailing stop order (separate from emergency SL)
    tp_id: str | None = None
    tp_price: float | None = None  # cached
    position_qty: float = 0.0
    entry_price: float = 0.0
    entry_time_ms: int = 0
    entry_fee: float = 0.0
    trailing_watermark: float = 0.0  # highest (long) or lowest (short) since entry
    cooldown_remaining: int = 0
    pending_reversal_id: str | None = None
    accumulated_funding: float = 0.0  # funding costs for current position

    @property
    def has_position(self) -> bool:
        return self.position_state != PositionState.FLAT

    @property
    def position_side(self) -> OrderSide | None:
        if self.position_state == PositionState.LONG:
            return OrderSide.BUY
        elif self.position_state == PositionState.SHORT:
            return OrderSide.SELL
        return None
