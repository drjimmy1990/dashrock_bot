"""Symbol registry — fetches and caches Binance exchange info.

Provides tick size, step size, min notional for order validation.
Works in both live mode (fetches from API) and paper mode (uses defaults).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    price_precision: int
    quantity_precision: int
    tick_size: float
    step_size: float
    min_notional: float
    min_qty: float


class SymbolRegistry:
    """In-memory cache of exchange symbol metadata."""

    def __init__(self) -> None:
        self._symbols: dict[str, SymbolInfo] = {}

    def load_from_exchange_info(self, exchange_info: dict) -> None:
        """Parse Binance exchange info response."""
        count = 0
        for s in exchange_info.get("symbols", []):
            # Only perpetuals, USDT-margined
            ctype = s.get("contractType")
            if ctype not in ("PERPETUAL", "TRADIFI_PERPETUAL") or s.get("quoteAsset") != "USDT":
                continue

            tick_size = 0.01
            step_size = 0.001
            min_notional = 5.0
            min_qty = 0.001

            for f in s.get("filters", []):
                ft = f.get("filterType")
                if ft == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", tick_size))
                elif ft == "LOT_SIZE":
                    step_size = float(f.get("stepSize", step_size))
                    min_qty = float(f.get("minQty", min_qty))
                elif ft == "MIN_NOTIONAL":
                    min_notional = float(f.get("notional", min_notional))

            si = SymbolInfo(
                symbol=s["symbol"],
                base_asset=s.get("baseAsset", ""),
                quote_asset=s.get("quoteAsset", ""),
                status=s.get("status", ""),
                price_precision=int(s.get("pricePrecision", 8)),
                quantity_precision=int(s.get("quantityPrecision", 8)),
                tick_size=tick_size,
                step_size=step_size,
                min_notional=min_notional,
                min_qty=min_qty,
            )
            self._symbols[si.symbol] = si
            count += 1

        log.info("SymbolRegistry: loaded %d USDT-M perpetual symbols", count)

    def load_defaults(self, symbols: list[str]) -> None:
        """Create default entries for paper mode (no API needed)."""
        for sym in symbols:
            if sym not in self._symbols:
                self._symbols[sym] = SymbolInfo(
                    symbol=sym, base_asset=sym.replace("USDT", ""),
                    quote_asset="USDT", status="TRADING",
                    price_precision=8, quantity_precision=8,
                    tick_size=0.01, step_size=0.001,
                    min_notional=5.0, min_qty=0.001,
                )

    async def load_from_binance(self, base_url: str = "https://fapi.binance.com") -> None:
        """Fetch real exchange info from Binance Futures REST API.

        Must be used in live/testnet mode to get accurate tick/step sizes.
        Without this, orders will be rejected for precision violations.
        """
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base_url}/fapi/v1/exchangeInfo")
            resp.raise_for_status()
            self.load_from_exchange_info(resp.json())
            log.info("Loaded exchange info from %s", base_url)

    def get(self, symbol: str) -> SymbolInfo | None:
        return self._symbols.get(symbol.upper())

    def all_symbols(self) -> list[str]:
        return sorted(s.symbol for s in self._symbols.values() if s.status == "TRADING")

    def round_price(self, symbol: str, price: float) -> float:
        info = self.get(symbol)
        if info is None:
            return price
        return round(round(price / info.tick_size) * info.tick_size, info.price_precision)

    def round_qty(self, symbol: str, qty: float) -> float:
        """Round quantity DOWN to step size (never round up)."""
        info = self.get(symbol)
        if info is None:
            return qty
        rounded = math.floor(qty / info.step_size) * info.step_size
        return round(rounded, info.quantity_precision)

    def validate_order(self, symbol: str, qty: float, price: float) -> str | None:
        """Return error string if order would be rejected, None if OK."""
        info = self.get(symbol)
        if info is None:
            return f"Unknown symbol: {symbol}"
        if qty < info.min_qty:
            return f"Qty {qty} below min {info.min_qty}"
        notional = qty * price
        if notional < info.min_notional:
            return f"Notional {notional:.2f} below min {info.min_notional}"
        return None
