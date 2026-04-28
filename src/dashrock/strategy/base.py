"""Strategy ABC — interface all trading strategies must implement.

Strategies are pluggable. The engine loads them by name from the registry.
Each strategy receives multi-timeframe candle data and returns desired orders.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from dashrock.core.types import Candle, DesiredOrders, Fill, PositionState


class Strategy(ABC):
    """Base class for all trading strategies."""

    @abstractmethod
    def name(self) -> str:
        """Unique name for this strategy (matches config.strategy.name)."""
        ...

    @abstractmethod
    def compute(
        self,
        symbol: str,
        candles: dict[str, list[Candle]],  # {timeframe: [candle_list]}
        position: PositionState,
        current_price: float,
    ) -> DesiredOrders:
        """Compute desired entry orders for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            candles: Multi-timeframe candle data. Primary TF is always present.
            position: Current position state (FLAT/LONG/SHORT)
            current_price: Latest close price for stale-breakout checks

        Returns:
            DesiredOrders describing which entry stop orders should be alive.
        """
        ...

    def on_fill(self, symbol: str, fill: Fill) -> None:
        """Called when an order fills. Override for stateful strategies."""
        pass

    def clear_state(self, symbol: str) -> None:
        """Reset any per-symbol cached state (e.g., fixed levels)."""
        pass

    def required_timeframes(self) -> list[str]:
        """Which timeframes this strategy needs candle data for.

        Default: only the primary timeframe configured in config.yaml.
        Override to add higher timeframes for multi-TF analysis.
        """
        return []
