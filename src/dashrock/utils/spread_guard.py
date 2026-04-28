"""Spread guard — blocks trading when spread is too wide."""

from __future__ import annotations

import math
from dataclasses import dataclass

from dashrock.config import SpreadCfg


@dataclass(frozen=True)
class SpreadCheckResult:
    passed: bool
    exceeded: bool
    threshold: float
    actual: float


def check_spread(cfg: SpreadCfg, spread: float, current_atr: float) -> SpreadCheckResult:
    if cfg.use_dynamic and not math.isnan(current_atr):
        threshold = current_atr * cfg.dynamic_atr_mult
    else:
        threshold = cfg.max_pips

    exceeded = spread > threshold
    passed = not exceeded or cfg.log_only
    return SpreadCheckResult(passed=passed, exceeded=exceeded, threshold=threshold, actual=spread)
