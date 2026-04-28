"""SQLAlchemy models for PostgreSQL (Supabase).

All tables the engine needs. Managed via Alembic migrations.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


class TradeModel(Base):
    """Completed (closed) trades."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=False)
    fees = Column(Float, nullable=False, default=0.0)
    funding_cost = Column(Float, nullable=False, default=0.0)
    exit_reason = Column(String(20), nullable=False)
    entry_time_ms = Column(BigInteger, nullable=False)
    exit_time_ms = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_trades_exit_time", "exit_time_ms"),
    )


class OrderModel(Base):
    """All orders placed (pending + historical)."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(50), unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    order_type = Column(String(25), nullable=False)
    stop_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False)
    status = Column(String(20), nullable=False)
    reduce_only = Column(Boolean, default=False)
    tag = Column(String(50), default="")
    created_at_ms = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_orders_symbol_status", "symbol", "status"),
    )


class EquitySnapshotModel(Base):
    """Periodic equity curve snapshots."""
    __tablename__ = "equity_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    equity_usd = Column(Float, nullable=False)
    timestamp_ms = Column(BigInteger, nullable=False, index=True)


class EngineStateModel(Base):
    """Persisted execution state per symbol — survives crashes."""
    __tablename__ = "engine_state"

    symbol = Column(String(20), primary_key=True)
    position_state = Column(String(10), nullable=False, default="FLAT")
    entry_buy_id = Column(String(50), nullable=True)
    entry_buy_stop_price = Column(Float, nullable=True)
    entry_sell_id = Column(String(50), nullable=True)
    entry_sell_stop_price = Column(Float, nullable=True)
    sl_id = Column(String(50), nullable=True)
    sl_price = Column(Float, nullable=True)
    tp_id = Column(String(50), nullable=True)
    tp_price = Column(Float, nullable=True)
    position_qty = Column(Float, default=0.0)
    entry_price = Column(Float, default=0.0)
    entry_time_ms = Column(BigInteger, default=0)
    entry_fee = Column(Float, default=0.0)
    trailing_watermark = Column(Float, default=0.0)
    cooldown_remaining = Column(Integer, default=0)
    pending_reversal_id = Column(String(50), nullable=True)
    accumulated_funding = Column(Float, default=0.0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class EventLogModel(Base):
    """Audit trail of engine events."""
    __tablename__ = "events_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(30), nullable=False)
    component = Column(String(30), nullable=False, default="engine")
    message = Column(Text, nullable=False)
    correlation_id = Column(String(12), default="")
    timestamp_ms = Column(BigInteger, nullable=False, index=True)


class ScannerSnapshotModel(Base):
    """Volatility scanner rankings."""
    __tablename__ = "scanner_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    score = Column(Float, nullable=False)
    natr = Column(Float, nullable=False)
    expansion = Column(Float, nullable=False)
    donchian_atr_ratio = Column(Float, nullable=False)
    timestamp_ms = Column(BigInteger, nullable=False, index=True)


class ConfigOverrideModel(Base):
    """Persistent config overrides from the dashboard."""
    __tablename__ = "config_overrides"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)  # JSON encoded
    updated_at_ms = Column(BigInteger, nullable=False)


class FundingRateModel(Base):
    """Historical funding rates per symbol."""
    __tablename__ = "funding_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    rate = Column(Float, nullable=False)
    funding_time_ms = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_funding_symbol_time", "symbol", "funding_time_ms"),
    )
