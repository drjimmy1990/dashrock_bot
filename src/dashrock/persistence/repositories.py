"""Repository pattern — clean data access layer for all DB operations.

Each method handles its own session lifecycle. The calling code
never deals with SQLAlchemy sessions directly.
"""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from dashrock.core.types import SymbolExecutionState, TradeRecord
from dashrock.persistence.database import Database
from dashrock.persistence.models import (
    ConfigOverrideModel,
    EngineStateModel,
    EquitySnapshotModel,
    EventLogModel,
    FundingRateModel,
    OrderModel,
    ScannerSnapshotModel,
    TradeModel,
)

log = logging.getLogger(__name__)


class Repository:
    """Data access layer — all DB reads/writes go through here."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ─── Trades ──────────────────────────────────────────

    async def insert_trade(self, trade: TradeRecord) -> int:
        async with self._db.session() as session:
            model = TradeModel(
                symbol=trade.symbol,
                side=trade.side,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                quantity=trade.quantity,
                realized_pnl=trade.realized_pnl,
                fees=trade.fees,
                funding_cost=trade.funding_cost,
                exit_reason=trade.exit_reason,
                entry_time_ms=trade.entry_time_ms,
                exit_time_ms=trade.exit_time_ms,
            )
            session.add(model)
            await session.commit()
            return model.id  # type: ignore[return-value]

    async def get_trades(
        self, symbol: str | None = None, limit: int = 50,
    ) -> list[TradeRecord]:
        async with self._db.session() as session:
            query = select(TradeModel).order_by(TradeModel.exit_time_ms.desc())
            if symbol:
                query = query.where(TradeModel.symbol == symbol)
            query = query.limit(limit)
            result = await session.execute(query)
            rows = result.scalars().all()
            return [
                TradeRecord(
                    id=r.id, symbol=r.symbol, side=r.side,
                    entry_price=r.entry_price, exit_price=r.exit_price,
                    quantity=r.quantity, realized_pnl=r.realized_pnl,
                    fees=r.fees, funding_cost=r.funding_cost,
                    exit_reason=r.exit_reason,
                    entry_time_ms=r.entry_time_ms, exit_time_ms=r.exit_time_ms,
                )
                for r in rows
            ]

    async def clear_trades(self) -> int:
        """Delete all trade records. Returns count of deleted rows."""
        async with self._db.session() as session:
            result = await session.execute(delete(TradeModel))
            await session.commit()
            count = result.rowcount  # type: ignore[union-attr]
            log.info("Cleared %d trade records from database", count)
            return count

    async def get_todays_realized_pnl(self) -> float:
        """Sum of realized PnL for trades closed today.

        NOTE: "Today" is defined as UTC midnight to now. This is intentional —
        Binance funding settlements and most exchange reporting use UTC.
        The safety circuit breaker (max_daily_loss_pct) therefore operates
        on UTC trading days, not the server's local timezone.
        """
        async with self._db.session() as session:
            # Start of today in ms
            today_start_ms = int(
                time.time() // 86400 * 86400 * 1000
            )
            result = await session.execute(
                select(func.coalesce(func.sum(TradeModel.realized_pnl), 0)).where(
                    TradeModel.exit_time_ms >= today_start_ms
                )
            )
            return float(result.scalar_one())

    async def get_consecutive_losses(self) -> int:
        """Count consecutive losing trades from most recent backwards."""
        async with self._db.session() as session:
            result = await session.execute(
                select(TradeModel.realized_pnl)
                .order_by(TradeModel.exit_time_ms.desc())
                .limit(50)
            )
            count = 0
            for (pnl,) in result:
                if pnl < 0:
                    count += 1
                else:
                    break
            return count

    # ─── Orders ──────────────────────────────────────────

    async def insert_order(
        self, *, order_id: str, symbol: str, side: str, order_type: str,
        stop_price: float | None, quantity: float, status: str,
        reduce_only: bool, tag: str, created_at_ms: int,
    ) -> None:
        async with self._db.session() as session:
            # Upsert: if order_id already exists, update status instead of crashing
            stmt = pg_insert(OrderModel).values(
                order_id=order_id, symbol=symbol, side=side,
                order_type=order_type, stop_price=stop_price,
                quantity=quantity, status=status, reduce_only=reduce_only,
                tag=tag, created_at_ms=created_at_ms,
            ).on_conflict_do_update(
                index_elements=["order_id"],
                set_={"status": status, "stop_price": stop_price, "quantity": quantity},
            )
            await session.execute(stmt)
            await session.commit()

    async def update_order_status(self, order_id: str, status: str) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(OrderModel)
                .where(OrderModel.order_id == order_id)
                .values(status=status)
            )
            await session.commit()

    async def get_known_order_ids(self, symbols: list[str]) -> set[str]:
        """Get all order IDs we know about (for reconciliation)."""
        async with self._db.session() as session:
            result = await session.execute(
                select(OrderModel.order_id).where(
                    OrderModel.symbol.in_(symbols),
                    OrderModel.status == "NEW",
                )
            )
            return {row[0] for row in result}

    # ─── Equity Snapshots ────────────────────────────────

    async def insert_equity_snapshot(self, equity_usd: float) -> None:
        async with self._db.session() as session:
            session.add(EquitySnapshotModel(
                equity_usd=equity_usd,
                timestamp_ms=int(time.time() * 1000),
            ))
            await session.commit()

    async def get_equity_snapshots(self, limit: int = 100) -> list[dict]:
        async with self._db.session() as session:
            result = await session.execute(
                select(EquitySnapshotModel)
                .order_by(EquitySnapshotModel.timestamp_ms.desc())
                .limit(limit)
            )
            return [
                {"equity_usd": r.equity_usd, "timestamp_ms": r.timestamp_ms}
                for r in result.scalars()
            ]

    async def get_equity_high_water(self) -> float:
        async with self._db.session() as session:
            result = await session.execute(
                select(func.coalesce(func.max(EquitySnapshotModel.equity_usd), 0))
            )
            return float(result.scalar_one())

    # ─── Engine State (Crash Recovery) ───────────────────

    async def save_engine_state(self, state: SymbolExecutionState) -> None:
        """Upsert execution state for a symbol (atomic, no race conditions)."""
        from dashrock.core.types import PositionState  # avoid circular

        pos_val = state.position_state.value if isinstance(state.position_state, Enum) else state.position_state
        values = dict(
            symbol=state.symbol,
            position_state=pos_val,
            entry_buy_id=state.entry_buy_id,
            entry_buy_stop_price=state.entry_buy_stop_price,
            entry_sell_id=state.entry_sell_id,
            entry_sell_stop_price=state.entry_sell_stop_price,
            sl_id=state.sl_id,
            sl_price=state.sl_price,
            tp_id=state.tp_id,
            tp_price=state.tp_price,
            position_qty=state.position_qty,
            entry_price=state.entry_price,
            entry_time_ms=state.entry_time_ms,
            entry_fee=state.entry_fee,
            trailing_watermark=state.trailing_watermark,
            cooldown_remaining=state.cooldown_remaining,
            pending_reversal_id=state.pending_reversal_id,
            accumulated_funding=state.accumulated_funding,
        )
        # All columns except the PK (symbol) get updated on conflict
        update_cols = {k: v for k, v in values.items() if k != "symbol"}

        stmt = pg_insert(EngineStateModel).values(**values).on_conflict_do_update(
            index_elements=["symbol"],
            set_=update_cols,
        )
        async with self._db.session() as session:
            await session.execute(stmt)
            await session.commit()

    async def load_engine_states(self) -> dict[str, SymbolExecutionState]:
        """Load all persisted execution states (for crash recovery)."""
        from dashrock.core.types import PositionState
        async with self._db.session() as session:
            result = await session.execute(select(EngineStateModel))
            states = {}
            for r in result.scalars():
                states[r.symbol] = SymbolExecutionState(
                    symbol=r.symbol,
                    position_state=PositionState(r.position_state),
                    entry_buy_id=r.entry_buy_id,
                    entry_buy_stop_price=r.entry_buy_stop_price,
                    entry_sell_id=r.entry_sell_id,
                    entry_sell_stop_price=r.entry_sell_stop_price,
                    sl_id=r.sl_id,
                    sl_price=r.sl_price,
                    tp_id=r.tp_id,
                    tp_price=r.tp_price,
                    position_qty=r.position_qty or 0.0,
                    entry_price=r.entry_price or 0.0,
                    entry_time_ms=r.entry_time_ms or 0,
                    entry_fee=r.entry_fee or 0.0,
                    trailing_watermark=r.trailing_watermark or 0.0,
                    cooldown_remaining=r.cooldown_remaining or 0,
                    pending_reversal_id=r.pending_reversal_id,
                    accumulated_funding=r.accumulated_funding or 0.0,
                )
            return states

    async def clear_engine_state(self, symbol: str) -> None:
        async with self._db.session() as session:
            await session.execute(
                delete(EngineStateModel).where(EngineStateModel.symbol == symbol)
            )
            await session.commit()

    async def clear_all_engine_states(self) -> None:
        async with self._db.session() as session:
            await session.execute(delete(EngineStateModel))
            await session.commit()

    # ─── Events Log ──────────────────────────────────────

    async def insert_event(
        self, *, event_type: str, component: str, message: str,
        correlation_id: str = "",
    ) -> None:
        async with self._db.session() as session:
            session.add(EventLogModel(
                event_type=event_type,
                component=component,
                message=message,
                correlation_id=correlation_id,
                timestamp_ms=int(time.time() * 1000),
            ))
            await session.commit()

    async def get_events(
        self, limit: int = 200, level: str | None = None, component: str | None = None,
    ) -> list[dict]:
        async with self._db.session() as session:
            query = select(EventLogModel).order_by(EventLogModel.timestamp_ms.desc())
            if level:
                query = query.where(EventLogModel.event_type == level)
            if component:
                query = query.where(EventLogModel.component == component)
            query = query.limit(limit)
            result = await session.execute(query)
            return [
                {
                    "id": r.id, "event_type": r.event_type,
                    "component": r.component, "message": r.message,
                    "correlation_id": r.correlation_id,
                    "timestamp_ms": r.timestamp_ms,
                }
                for r in result.scalars()
            ]

    # ─── Scanner ─────────────────────────────────────────

    async def insert_scanner_snapshot(
        self, *, symbol: str, score: float, natr: float,
        expansion: float, donchian_atr_ratio: float,
    ) -> None:
        async with self._db.session() as session:
            session.add(ScannerSnapshotModel(
                symbol=symbol, score=score, natr=natr,
                expansion=expansion, donchian_atr_ratio=donchian_atr_ratio,
                timestamp_ms=int(time.time() * 1000),
            ))
            await session.commit()

    # ─── Config Overrides ────────────────────────────────

    async def save_config_override(self, key: str, value: Any) -> None:
        async with self._db.session() as session:
            existing = await session.get(ConfigOverrideModel, key)
            now_ms = int(time.time() * 1000)
            encoded = json.dumps(value)
            if existing:
                existing.value = encoded
                existing.updated_at_ms = now_ms
            else:
                session.add(ConfigOverrideModel(
                    key=key, value=encoded, updated_at_ms=now_ms,
                ))
            await session.commit()

    async def load_config_overrides(self) -> dict[str, Any]:
        async with self._db.session() as session:
            result = await session.execute(select(ConfigOverrideModel))
            return {
                r.key: json.loads(r.value) for r in result.scalars()
            }

    async def delete_config_override(self, key: str) -> None:
        async with self._db.session() as session:
            await session.execute(
                delete(ConfigOverrideModel).where(ConfigOverrideModel.key == key)
            )
            await session.commit()

    # ─── Funding Rates ───────────────────────────────────

    async def insert_funding_rate(
        self, symbol: str, rate: float, funding_time_ms: int,
    ) -> None:
        async with self._db.session() as session:
            session.add(FundingRateModel(
                symbol=symbol, rate=rate, funding_time_ms=funding_time_ms,
            ))
            await session.commit()

    # ─── Reset ───────────────────────────────────────────

    async def reset_all(self) -> None:
        """Wipe ALL trading data. Use with caution."""
        async with self._db.session() as session:
            for model in [
                TradeModel, OrderModel, EquitySnapshotModel,
                EngineStateModel, EventLogModel, ScannerSnapshotModel,
                FundingRateModel,
            ]:
                await session.execute(delete(model))
            await session.commit()
        log.warning("All trading data has been wiped!")
