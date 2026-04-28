"""Portfolio-level risk management.

Enforces:
- Maximum number of simultaneous open positions
- Maximum total leveraged exposure as % of equity
- Maximum single-symbol exposure as % of equity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from dashrock.config import PortfolioRiskCfg
from dashrock.core.types import SymbolExecutionState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortfolioCheckResult:
    allowed: bool
    reason: str


class PortfolioRiskManager:
    """Checks portfolio-level constraints before new position entry."""

    def __init__(self, cfg: PortfolioRiskCfg) -> None:
        self.cfg = cfg

    def check_new_entry(
        self,
        symbol: str,
        proposed_notional: float,
        equity: float,
        current_states: dict[str, SymbolExecutionState],
        leverage: int,
    ) -> PortfolioCheckResult:
        """Check if a new position on `symbol` is allowed given portfolio constraints.

        Args:
            symbol: The symbol we want to enter
            proposed_notional: Proposed position size in USD
            equity: Current equity in USD
            current_states: All current execution states
            leverage: Trading leverage

        Returns:
            PortfolioCheckResult with allowed=True/False and reason
        """
        if equity <= 0:
            return PortfolioCheckResult(False, "equity is zero or negative")

        # Count currently open positions (excluding the proposed one)
        open_positions = [
            s for s in current_states.values()
            if s.has_position and s.symbol != symbol
        ]
        open_count = len(open_positions)

        # Check max open positions
        if open_count >= self.cfg.max_open_positions:
            return PortfolioCheckResult(
                False,
                f"max_open_positions: {open_count} >= {self.cfg.max_open_positions}",
            )

        # Check per-symbol exposure
        symbol_exposure_pct = (proposed_notional / equity) * 100
        if symbol_exposure_pct > self.cfg.max_per_symbol_exposure_pct:
            return PortfolioCheckResult(
                False,
                f"per_symbol_exposure: {symbol_exposure_pct:.1f}% > "
                f"{self.cfg.max_per_symbol_exposure_pct}%",
            )

        # Check total exposure (existing + proposed)
        total_exposure = sum(
            s.position_qty * s.entry_price
            for s in open_positions
        )
        total_exposure += proposed_notional
        total_exposure_pct = (total_exposure / equity) * 100

        if total_exposure_pct > self.cfg.max_total_exposure_pct:
            return PortfolioCheckResult(
                False,
                f"total_exposure: {total_exposure_pct:.1f}% > "
                f"{self.cfg.max_total_exposure_pct}%",
            )

        return PortfolioCheckResult(True, "")
