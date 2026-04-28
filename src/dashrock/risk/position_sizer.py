"""Risk-per-trade position sizer.

Sizes positions so that a stop-loss hit equals a fixed % of equity lost.
This replaces the v1 "margin × leverage = notional" approach which ignored SL distance.
"""

from __future__ import annotations

import logging

from dashrock.config import SizingCfg

log = logging.getLogger(__name__)


def size_for_risk(
    cfg: SizingCfg,
    equity: float,
    entry_price: float,
    sl_price: float,
) -> float:
    """Calculate position size (quantity in base asset) based on risk.

    If SL hit, the loss = risk_per_trade_pct of equity.

    Args:
        cfg: Sizing configuration
        equity: Current account equity in USD
        entry_price: Expected entry price
        sl_price: Stop-loss price

    Returns:
        Quantity in base asset (e.g., 0.05 BTC)
    """
    if cfg.mode == "fixed":
        notional = cfg.fallback_fixed_usd * cfg.leverage
        if entry_price <= 0:
            return 0.0
        return notional / entry_price

    if cfg.mode == "risk_per_trade":
        if equity <= 0 or entry_price <= 0:
            return 0.0

        sl_distance = abs(entry_price - sl_price)
        if sl_distance == 0:
            log.warning("SL distance is 0 — cannot size position")
            return 0.0

        # How much USD we're willing to lose
        risk_amount = equity * (cfg.risk_per_trade_pct / 100.0)

        # Quantity where loss = risk_amount if SL is hit
        qty = risk_amount / sl_distance

        log.debug(
            "Risk sizing: equity=$%.2f risk=%.1f%% ($%.2f) "
            "entry=%.8g sl=%.8g distance=%.8g qty=%.8g",
            equity, cfg.risk_per_trade_pct, risk_amount,
            entry_price, sl_price, sl_distance, qty,
        )
        return qty

    if cfg.mode == "equity_fraction":
        # Simple fraction of equity as notional
        if equity <= 0 or entry_price <= 0:
            return 0.0
        notional = equity * (cfg.risk_per_trade_pct / 100.0) * cfg.leverage
        return notional / entry_price

    log.error("Unknown sizing mode: %s", cfg.mode)
    return 0.0
