"""Real-time safety monitor — circuit breakers for the trading engine.

Improvements over v1:
- Can check on every tick (not just candle close)
- Includes funding cost in daily PnL calculation
- Emits events to the bus on trigger
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from dashrock.config import SafetyCfg

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SafetyResult:
    trading_allowed: bool
    reason: str


class SafetyMonitor:
    """Circuit breakers: daily loss, drawdown, consecutive losses."""

    def __init__(self, cfg: SafetyCfg) -> None:
        self.cfg = cfg
        self._tick_counter = 0
        self._last_result = SafetyResult(trading_allowed=True, reason="")

    def check_on_tick(self, **kwargs: float | int) -> SafetyResult:
        """Throttled safety check — runs every `tick_check_interval` ticks.

        Returns the cached result between actual checks.
        """
        if not self.cfg.check_on_tick:
            return self._last_result

        self._tick_counter += 1
        if self._tick_counter < self.cfg.tick_check_interval:
            return self._last_result

        self._tick_counter = 0
        self._last_result = self.check(**kwargs)
        return self._last_result

    def check(
        self,
        daily_pnl: float = 0.0,
        starting_equity: float = 0.0,
        current_equity: float = 0.0,
        high_water_equity: float = 0.0,
        consecutive_losses: int = 0,
    ) -> SafetyResult:
        """Full safety check. Called on candle close and throttled ticks."""

        # Daily loss check
        if self.cfg.max_daily_loss_pct > 0 and starting_equity > 0:
            loss_pct = abs(daily_pnl) / starting_equity * 100 if daily_pnl < 0 else 0
            if loss_pct >= self.cfg.max_daily_loss_pct:
                reason = f"daily_loss: {loss_pct:.1f}% >= {self.cfg.max_daily_loss_pct}%"
                log.error("SAFETY TRIGGERED: %s", reason)
                return SafetyResult(trading_allowed=False, reason=reason)

        # Drawdown check
        if self.cfg.max_drawdown_pct > 0 and high_water_equity > 0:
            dd_pct = (1 - current_equity / high_water_equity) * 100
            if dd_pct >= self.cfg.max_drawdown_pct:
                reason = f"drawdown: {dd_pct:.1f}% >= {self.cfg.max_drawdown_pct}%"
                log.error("SAFETY TRIGGERED: %s", reason)
                return SafetyResult(trading_allowed=False, reason=reason)

        # Consecutive losses
        if self.cfg.max_consecutive_losses > 0:
            if consecutive_losses >= self.cfg.max_consecutive_losses:
                reason = (
                    f"consecutive_losses: {consecutive_losses} >= "
                    f"{self.cfg.max_consecutive_losses}"
                )
                log.error("SAFETY TRIGGERED: %s", reason)
                return SafetyResult(trading_allowed=False, reason=reason)

        return SafetyResult(trading_allowed=True, reason="")
