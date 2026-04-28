"""Volatility scanner — ranks symbols by breakout potential."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from dashrock.config import VolatilityCfg
from dashrock.core.types import Candle
from dashrock.strategy.indicators import atr, highest_high, lowest_low, natr


@dataclass(frozen=True)
class ScannerRank:
    symbol: str
    score: float
    natr: float
    expansion: float
    donchian_atr_ratio: float


def rank_symbols(
    data: dict[str, Sequence[Candle]],
    cfg: VolatilityCfg,
) -> list[ScannerRank]:
    """Rank symbols by volatility score, filtering below min_score."""
    results: list[ScannerRank] = []

    for symbol, candles in data.items():
        natr_val = natr(candles, 14)
        if math.isnan(natr_val):
            continue

        atr14 = atr(candles, 14)
        atr50 = atr(candles, 50)
        expansion = (atr14 / atr50) if (not math.isnan(atr50) and atr50 > 0) else 1.0

        n = min(len(candles), 14)
        hh = highest_high(candles, n)
        ll = lowest_low(candles, n)
        donchian_range = hh - ll
        donchian_atr = (donchian_range / atr14) if atr14 > 0 else 0.0

        if cfg.mode == "normalized_atr":
            score = natr_val
        else:
            w = cfg.weights
            score = w.natr * natr_val + w.expansion * expansion + w.donchian_atr * donchian_atr

        if score < cfg.min_score:
            continue

        results.append(ScannerRank(
            symbol=symbol, score=score, natr=natr_val,
            expansion=expansion, donchian_atr_ratio=donchian_atr,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results
