"""Order reconciliation — diff exchange state against our DB."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from dashrock.adapters.base import ExecutionAdapter
from dashrock.core.types import LiveOrder
from dashrock.persistence.repositories import Repository

log = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    orphans: list[LiveOrder] = field(default_factory=list)
    missing: set[str] = field(default_factory=set)


def diff_orders(
    exchange_orders: list[LiveOrder],
    known_db_ids: set[str],
) -> ReconciliationResult:
    exchange_ids = {o.order_id for o in exchange_orders}
    orphans = [o for o in exchange_orders if o.order_id not in known_db_ids]
    missing = known_db_ids - exchange_ids
    return ReconciliationResult(orphans=orphans, missing=missing)


async def reconcile(
    adapter: ExecutionAdapter,
    symbols: list[str],
    repo: Repository,
    orphan_policy: str = "alert_only",
) -> ReconciliationResult:
    """Full reconciliation across all symbols."""
    all_exchange_orders: list[LiveOrder] = []
    for symbol in symbols:
        orders = await adapter.get_open_orders(symbol)
        all_exchange_orders.extend(orders)

    known_ids = await repo.get_known_order_ids(symbols)
    result = diff_orders(all_exchange_orders, known_ids)

    if result.orphans:
        log.warning(
            "Reconciliation: %d orphan orders on exchange: %s",
            len(result.orphans), [o.order_id for o in result.orphans],
        )
        if orphan_policy == "cancel":
            for o in result.orphans:
                log.warning("Cancelling orphan %s on %s", o.order_id, o.symbol)
                await adapter.cancel_order(o.symbol, o.order_id)

    if result.missing:
        log.warning(
            "Reconciliation: %d orders in DB but not on exchange: %s",
            len(result.missing), result.missing,
        )
        # Query exchange for actual order status instead of blindly marking CANCELED
        for order_id in result.missing:
            await repo.update_order_status(order_id, "UNKNOWN_MISSING")

    return result
