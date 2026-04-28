"""Trailing stop logic — extracted from execution manager for testability.

Supports two modes:
- step: move SL by `step_pips` when price moves favorably by `step_pips`
- activation_trail: activate trailing after `activation_pips` profit, then trail at `stop_pips`
"""

from __future__ import annotations

import logging

from dashrock.config import TrailingCfg
from dashrock.core.types import OrderSide, PositionState, SymbolExecutionState

log = logging.getLogger(__name__)


class TrailingManager:
    """Manages trailing stop logic for all symbols."""

    def __init__(self, cfg: TrailingCfg) -> None:
        self._cfg = cfg
        self._active: set[str] = set()  # symbols with active trailing

    def initialize(self, symbol: str, entry_price: float, side: OrderSide) -> None:
        """Called when a new position opens."""
        self._active.discard(symbol)

    def is_active(self, symbol: str) -> bool:
        return symbol in self._active

    def clear(self, symbol: str) -> None:
        self._active.discard(symbol)

    def update(
        self,
        *,
        symbol: str,
        current_price: float,
        entry_price: float,
        current_sl_price: float,
        position_side: OrderSide | None,
        state: SymbolExecutionState,
    ) -> float | None:
        """Calculate new SL price based on trailing logic.

        Returns new SL price if it should be moved, None if no change needed.
        """
        if not self._cfg.enabled or self._cfg.mode == "off":
            return None

        if position_side is None:
            return None

        is_long = position_side == OrderSide.BUY

        if self._cfg.mode == "step":
            return self._step_trail(
                symbol, current_price, entry_price, current_sl_price, is_long, state,
            )
        elif self._cfg.mode == "activation_trail":
            return self._activation_trail(
                symbol, current_price, entry_price, current_sl_price, is_long, state,
            )
        return None

    def _step_trail(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        current_sl_price: float,
        is_long: bool,
        state: SymbolExecutionState,
    ) -> float | None:
        """Step trailing: move SL by step_pips when price gains step_pips."""
        if self._cfg.use_pct_pips:
            step = entry_price * (self._cfg.step_pips / 100.0)
            stop_distance = entry_price * (self._cfg.stop_pips / 100.0)
        else:
            step = self._cfg.step_pips
            stop_distance = self._cfg.stop_pips

        if step <= 0:
            return None

        # Update watermark
        if is_long:
            if current_price > state.trailing_watermark:
                state.trailing_watermark = current_price
            watermark = state.trailing_watermark
            # Calculate how many steps the price has moved from entry
            steps = int((watermark - entry_price) / step)
            if steps <= 0:
                return None
            new_sl = entry_price + (steps * step) - stop_distance
            if new_sl > current_sl_price:
                self._active.add(symbol)
                return new_sl
        else:
            if current_price < state.trailing_watermark or state.trailing_watermark == 0:
                state.trailing_watermark = current_price
            watermark = state.trailing_watermark
            steps = int((entry_price - watermark) / step)
            if steps <= 0:
                return None
            new_sl = entry_price - (steps * step) + stop_distance
            if new_sl < current_sl_price or current_sl_price == 0:
                self._active.add(symbol)
                return new_sl

        return None

    def _activation_trail(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        current_sl_price: float,
        is_long: bool,
        state: SymbolExecutionState,
    ) -> float | None:
        """Activation trail: activate after X pips profit, then trail at Y pips."""
        if self._cfg.use_pct_pips:
            activation = entry_price * (self._cfg.activation_pips / 100.0)
            trail_distance = entry_price * (self._cfg.stop_pips / 100.0)
        else:
            activation = self._cfg.activation_pips
            trail_distance = self._cfg.stop_pips

        if is_long:
            if current_price > state.trailing_watermark:
                state.trailing_watermark = current_price
            profit = state.trailing_watermark - entry_price
            if profit < activation:
                return None  # not yet activated
            self._active.add(symbol)
            new_sl = state.trailing_watermark - trail_distance
            if new_sl > current_sl_price:
                return new_sl
        else:
            if current_price < state.trailing_watermark or state.trailing_watermark == 0:
                state.trailing_watermark = current_price
            profit = entry_price - state.trailing_watermark
            if profit < activation:
                return None
            self._active.add(symbol)
            new_sl = state.trailing_watermark + trail_distance
            if new_sl < current_sl_price or current_sl_price == 0:
                return new_sl

        return None
