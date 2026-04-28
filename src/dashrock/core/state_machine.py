"""Engine state machine — controls lifecycle transitions.

States:
    INITIALIZING → READY → RUNNING → PAUSED → STOPPED
                                   ↘ ERROR
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

log = logging.getLogger(__name__)


class EngineStatus(str, Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


# Valid transitions: {from_state: [allowed_to_states]}
_TRANSITIONS: dict[EngineStatus, list[EngineStatus]] = {
    EngineStatus.INITIALIZING: [EngineStatus.READY, EngineStatus.ERROR],
    EngineStatus.READY: [EngineStatus.RUNNING, EngineStatus.PAUSED, EngineStatus.STOPPED, EngineStatus.ERROR],
    EngineStatus.RUNNING: [EngineStatus.PAUSED, EngineStatus.STOPPED, EngineStatus.ERROR],
    EngineStatus.PAUSED: [EngineStatus.RUNNING, EngineStatus.STOPPED, EngineStatus.ERROR],
    EngineStatus.STOPPED: [EngineStatus.INITIALIZING],
    EngineStatus.ERROR: [EngineStatus.STOPPED, EngineStatus.INITIALIZING],
}

StateChangeCallback = Callable[[EngineStatus, EngineStatus, str], None]


class EngineStateMachine:
    """Thread-safe engine state machine with transition guards and callbacks."""

    def __init__(self) -> None:
        self._status = EngineStatus.INITIALIZING
        self._callbacks: list[StateChangeCallback] = []
        self._error_message: str = ""

    @property
    def status(self) -> EngineStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status == EngineStatus.RUNNING

    @property
    def is_trading_allowed(self) -> bool:
        return self._status == EngineStatus.RUNNING

    @property
    def error_message(self) -> str:
        return self._error_message

    def on_state_change(self, callback: StateChangeCallback) -> None:
        """Register a callback fired on every state transition."""
        self._callbacks.append(callback)

    def transition(self, to: EngineStatus, reason: str = "") -> bool:
        """Attempt a state transition. Returns True if successful."""
        allowed = _TRANSITIONS.get(self._status, [])
        if to not in allowed:
            log.warning(
                "Invalid state transition: %s → %s (allowed: %s) reason: %s",
                self._status.value, to.value, [s.value for s in allowed], reason,
            )
            return False

        old = self._status
        self._status = to

        if to == EngineStatus.ERROR:
            self._error_message = reason
        else:
            self._error_message = ""

        log.info("Engine state: %s → %s (%s)", old.value, to.value, reason or "no reason")

        for cb in self._callbacks:
            try:
                cb(old, to, reason)
            except Exception:
                log.exception("State change callback error")

        return True

    def mark_ready(self, reason: str = "initialization complete") -> bool:
        return self.transition(EngineStatus.READY, reason)

    def start(self, reason: str = "engine started") -> bool:
        return self.transition(EngineStatus.RUNNING, reason)

    def pause(self, reason: str = "paused") -> bool:
        return self.transition(EngineStatus.PAUSED, reason)

    def resume(self, reason: str = "resumed") -> bool:
        return self.transition(EngineStatus.RUNNING, reason)

    def stop(self, reason: str = "shutdown") -> bool:
        return self.transition(EngineStatus.STOPPED, reason)

    def error(self, reason: str) -> bool:
        return self.transition(EngineStatus.ERROR, reason)
