"""Strategy registry — discovers and loads strategy plugins by name."""

from __future__ import annotations

import logging
from typing import Any

from dashrock.strategy.base import Strategy

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type[Strategy]] = {}


def register(name: str, cls: type[Strategy]) -> None:
    """Register a strategy class under the given name."""
    _REGISTRY[name] = cls
    log.debug("Registered strategy: %s", name)


def create(name: str, params: dict[str, Any] | None = None) -> Strategy:
    """Create a strategy instance by name with optional params."""
    cls = _REGISTRY.get(name)
    if cls is None:
        available = list(_REGISTRY.keys())
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {available}"
        )
    return cls(**(params or {}))


def available() -> list[str]:
    """List all registered strategy names."""
    return sorted(_REGISTRY.keys())


def _auto_register() -> None:
    """Register built-in strategies."""
    from dashrock.strategy.donchian_breakout import DonchianBreakoutStrategy  # noqa: F811
    register("donchian_breakout", DonchianBreakoutStrategy)


# Auto-register built-in strategies on import
_auto_register()
