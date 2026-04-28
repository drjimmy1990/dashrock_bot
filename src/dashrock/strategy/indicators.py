"""Technical indicator library.

Pure functions operating on candle sequences. No side effects.
All functions return math.nan when insufficient data.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from dashrock.core.types import Candle


def highest_high(candles: Sequence[Candle], window: int) -> float:
    """Highest high of the last `window` candles."""
    if window <= 0 or len(candles) < window:
        return math.nan
    return max(c.high for c in candles[-window:])


def lowest_low(candles: Sequence[Candle], window: int) -> float:
    """Lowest low of the last `window` candles."""
    if window <= 0 or len(candles) < window:
        return math.nan
    return min(c.low for c in candles[-window:])


def atr(candles: Sequence[Candle], period: int) -> float:
    """Wilder's ATR. Returns NaN if not enough data."""
    if period <= 0 or len(candles) < period + 1:
        return math.nan

    def true_range(curr: Candle, prev: Candle) -> float:
        return max(
            curr.high - curr.low,
            abs(curr.high - prev.close),
            abs(curr.low - prev.close),
        )

    trs = [true_range(candles[i], candles[i - 1]) for i in range(1, len(candles))]
    atr_val = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


def natr(candles: Sequence[Candle], period: int = 14) -> float:
    """Normalized ATR = ATR / close * 100."""
    atr_val = atr(candles, period)
    if math.isnan(atr_val) or not candles:
        return math.nan
    close = candles[-1].close
    return (atr_val / close) * 100 if close > 0 else math.nan


def adx(candles: Sequence[Candle], period: int = 14) -> float:
    """Average Directional Index. Returns NaN if not enough data.

    Measures trend strength regardless of direction.
    ADX > 25 = trending, ADX < 20 = ranging.
    """
    if len(candles) < period * 2 + 1:
        return math.nan

    # Calculate +DM and -DM
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr_list: list[float] = []

    for i in range(1, len(candles)):
        high_diff = candles[i].high - candles[i - 1].high
        low_diff = candles[i - 1].low - candles[i].low
        plus_dm.append(max(high_diff, 0) if high_diff > low_diff else 0)
        minus_dm.append(max(low_diff, 0) if low_diff > high_diff else 0)
        tr_list.append(max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close),
        ))

    # Wilder smoothing
    def wilder_smooth(values: list[float], p: int) -> list[float]:
        result = [sum(values[:p])]
        for v in values[p:]:
            result.append(result[-1] - result[-1] / p + v)
        return result

    smoothed_tr = wilder_smooth(tr_list, period)
    smoothed_plus_dm = wilder_smooth(plus_dm, period)
    smoothed_minus_dm = wilder_smooth(minus_dm, period)

    # +DI and -DI
    dx_values: list[float] = []
    for i in range(len(smoothed_tr)):
        tr_val = smoothed_tr[i]
        if tr_val == 0:
            continue
        plus_di = (smoothed_plus_dm[i] / tr_val) * 100
        minus_di = (smoothed_minus_dm[i] / tr_val) * 100
        di_sum = plus_di + minus_di
        if di_sum > 0:
            dx_values.append(abs(plus_di - minus_di) / di_sum * 100)

    if len(dx_values) < period:
        return math.nan

    # ADX = smoothed average of DX
    adx_val = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx_val = (adx_val * (period - 1) + dx) / period

    return adx_val


def bollinger_bandwidth(
    candles: Sequence[Candle], period: int = 20, std_dev: float = 2.0,
) -> float:
    """Bollinger Band width as a percentage of the middle band.

    Low values indicate a squeeze (consolidation before breakout).
    """
    if len(candles) < period:
        return math.nan

    closes = [c.close for c in candles[-period:]]
    mean = sum(closes) / len(closes)
    if mean == 0:
        return math.nan

    variance = sum((c - mean) ** 2 for c in closes) / len(closes)
    std = variance ** 0.5

    upper = mean + std_dev * std
    lower = mean - std_dev * std
    return (upper - lower) / mean * 100
