"""Pydantic response schemas — typed API responses."""

from __future__ import annotations

from pydantic import BaseModel


class StatusResponse(BaseModel):
    engine_state: str
    mode: str | None
    is_running: bool
    restart_required: bool


class HealthResponse(BaseModel):
    status: str
    engine_state: str
    db_connected: bool
    ws_connected: bool
    uptime_seconds: float


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TradeResponse(BaseModel):
    id: int | None
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    realized_pnl: float
    fees: float
    funding_cost: float
    exit_reason: str
    entry_time_ms: int
    exit_time_ms: int


class PositionResponse(BaseModel):
    symbol: str
    side: str | None
    quantity: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    sl_price: float
    tp_price: float
    trailing_active: bool
    trailing_watermark: float
    opened_at_ms: int


class OrderResponse(BaseModel):
    order_id: str
    symbol: str
    side: str
    order_type: str
    stop_price: float | None
    quantity: float
    status: str
    reduce_only: bool
    tag: str


class PnlResponse(BaseModel):
    realized_pnl_today: float
    equity_high_water: float
    consecutive_losses: int


class EquitySnapshotResponse(BaseModel):
    equity_usd: float
    timestamp_ms: int


class ScannerResponse(BaseModel):
    symbol: str
    score: float
    natr: float
    expansion: float
    donchian_atr_ratio: float


class MessageResponse(BaseModel):
    message: str


class CloseAllResponse(BaseModel):
    cancelled_orders: int
    closed_positions: int


class PositionModeRequest(BaseModel):
    hedge_mode: bool
