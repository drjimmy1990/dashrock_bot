"""Donchian Channel Breakout Strategy — the default strategy plugin.

Ported from v1 and enhanced with:
- Multi-timeframe candle awareness (uses primary TF for signals)
- Regime detection integration (skip ranging markets via ADX)
- Clean separation from execution logic
"""

from __future__ import annotations

import logging
import math
import time

from dashrock.config import StrategyCfg
from dashrock.core.types import (
    Candle,
    DesiredOrders,
    Fill,
    OrderIntent,
    OrderSide,
    OrderType,
    PositionState,
)
from dashrock.strategy.base import Strategy
from dashrock.strategy.indicators import adx, highest_high, lowest_low

log = logging.getLogger(__name__)


class DonchianBreakoutStrategy(Strategy):
    """Place Buy Stop above Highest High, Sell Stop below Lowest Low.

    Parameters (from StrategyCfg):
        lookback_candles: Window size for HH/LL calculation
        offset_pips: Offset added beyond HH/LL (pct if use_pct_pips)
        pending_refresh_mode: dynamic | fixed | hybrid_tighter
        min_channel_width_pct: Minimum HH-LL as % of mid-price
    """

    def __init__(self, **kwargs: object) -> None:
        # Strategy params come from config, but can be overridden via kwargs
        self._cfg: StrategyCfg | None = None
        self._fixed_levels: dict[str, tuple[float, float]] = {}  # symbol -> (hh, ll)

    def configure(self, cfg: StrategyCfg) -> None:
        """Set config after construction (called by the engine)."""
        self._cfg = cfg

    def name(self) -> str:
        return "donchian_breakout"

    def compute(
        self,
        symbol: str,
        candles: dict[str, list[Candle]],
        position: PositionState,
        current_price: float,
    ) -> DesiredOrders:
        if self._cfg is None:
            raise RuntimeError("Strategy not configured. Call configure() first.")
        cfg = self._cfg

        # Use the primary timeframe's candles (first key)
        primary_tf = next(iter(candles))
        window = candles[primary_tf]

        # Need enough data
        n = cfg.lookback_candles
        if len(window) < n:
            log.debug("%s: not enough candles (%d < %d)", symbol, len(window), n)
            return DesiredOrders(symbol=symbol, buy_stop=None, sell_stop=None)

        # Regime detection: skip if market is ranging
        if cfg.regime_detection.enabled and cfg.regime_detection.skip_ranging:
            adx_val = adx(window, cfg.regime_detection.adx_period)
            if not math.isnan(adx_val) and adx_val < cfg.regime_detection.adx_trending_threshold:
                log.info(
                    "%s: RANGING market detected (ADX=%.1f < %.1f), skipping entry",
                    symbol, adx_val, cfg.regime_detection.adx_trending_threshold,
                )
                return DesiredOrders(symbol=symbol, buy_stop=None, sell_stop=None)

        # Use the last N closed candles for HH/LL (including the most recent)
        lookback = window[-n:]
        trigger = window[-1]

        hh = highest_high(lookback, n)
        ll = lowest_low(lookback, n)

        if math.isnan(hh) or math.isnan(ll):
            return DesiredOrders(symbol=symbol, buy_stop=None, sell_stop=None)

        # Min channel width guard
        mid = (hh + ll) / 2
        if mid > 0:
            width_pct = (hh - ll) / mid * 100
            if width_pct < cfg.min_channel_width_pct:
                log.debug(
                    "%s: channel too narrow (%.4f%% < %.4f%%)",
                    symbol, width_pct, cfg.min_channel_width_pct,
                )
                return DesiredOrders(symbol=symbol, buy_stop=None, sell_stop=None)

        # Refresh mode logic
        if cfg.pending_refresh_mode == "fixed":
            if symbol in self._fixed_levels:
                hh, ll = self._fixed_levels[symbol]
            else:
                self._fixed_levels[symbol] = (hh, ll)
        elif cfg.pending_refresh_mode == "hybrid_tighter":
            if symbol in self._fixed_levels:
                old_hh, old_ll = self._fixed_levels[symbol]
                hh = min(hh, old_hh)  # can only tighten
                ll = max(ll, old_ll)
            self._fixed_levels[symbol] = (hh, ll)
        # else: dynamic — always use fresh levels

        # Calculate stop prices with offset
        if cfg.use_pct_pips:
            offset_buy = hh * (cfg.offset_pips / 100)
            offset_sell = ll * (cfg.offset_pips / 100)
        else:
            offset_buy = cfg.offset_pips
            offset_sell = cfg.offset_pips

        buy_price = hh + offset_buy
        sell_price = ll - offset_sell

        # Ensure buy stop is ABOVE current price (otherwise it fills immediately
        # as a market order). Use trigger candle's high + offset as minimum.
        # A minimum buffer of 0.01% prevents Binance -2021 "would immediately trigger"
        # when offset_pips is 0 or very small.
        min_buffer_pct = max(cfg.offset_pips if cfg.use_pct_pips else 0.01, 0.01)
        if buy_price <= current_price:
            log.info(
                "%s: buy_price %.8g <= current_price %.8g, adjusting to candle high + offset",
                symbol, buy_price, current_price,
            )
            buy_price = trigger.high + offset_buy
            if buy_price <= current_price:
                buy_price = current_price * (1 + min_buffer_pct / 100)

        # Ensure sell stop is BELOW current price
        if sell_price >= current_price:
            log.info(
                "%s: sell_price %.8g >= current_price %.8g, adjusting to candle low - offset",
                symbol, sell_price, current_price,
            )
            sell_price = trigger.low - offset_sell
            if sell_price >= current_price:
                sell_price = current_price * (1 - min_buffer_pct / 100)

        buy_stop = OrderIntent(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.STOP_MARKET,
            stop_price=buy_price,
            quantity=0,  # will be filled by risk module
            tag=f"entry_buy_stop_{int(time.time()*1000)}",
        )

        sell_stop = OrderIntent(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            stop_price=sell_price,
            quantity=0,  # will be filled by risk module
            tag=f"entry_sell_stop_{int(time.time()*1000)}",
        )

        log.info(
            "%s: HH=%.8g LL=%.8g buy_stop=%.8g sell_stop=%.8g current=%.8g",
            symbol, hh, ll, buy_price, sell_price, current_price,
        )

        return DesiredOrders(
            symbol=symbol,
            buy_stop=buy_stop,
            sell_stop=sell_stop,
            reference_price=trigger.close,
        )

    def on_fill(self, symbol: str, fill: Fill) -> None:
        """On fill, clear fixed levels so next compute starts fresh."""
        self._fixed_levels.pop(symbol, None)

    def clear_state(self, symbol: str) -> None:
        self._fixed_levels.pop(symbol, None)
