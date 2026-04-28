"""Dependency injection — shared engine state for API routes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dashrock.adapters.base import ExecutionAdapter
    from dashrock.config import Config
    from dashrock.core.state_machine import EngineStateMachine
    from dashrock.execution.manager import ExecutionManager
    from dashrock.market.data_service import MarketDataService
    from dashrock.market.symbol_registry import SymbolRegistry
    from dashrock.notifications.notifier import Notifier
    from dashrock.persistence.database import Database
    from dashrock.persistence.repositories import Repository
    from dashrock.risk.safety import SafetyMonitor
    from dashrock.strategy.base import Strategy


@dataclass
class EngineState:
    """Shared mutable container for all engine components.

    Populated by Application at startup, read by API endpoints.
    """
    state_machine: "EngineStateMachine | None" = None
    adapter: "ExecutionAdapter | None" = None
    manager: "ExecutionManager | None" = None
    db: "Database | None" = None
    repo: "Repository | None" = None
    notifier: "Notifier | None" = None
    strategy: "Strategy | None" = None
    safety: "SafetyMonitor | None" = None
    config: "Config | None" = None
    registry: "SymbolRegistry | None" = None
    md: "MarketDataService | None" = None
    config_path: Path | None = None
    start_time: float = 0.0
