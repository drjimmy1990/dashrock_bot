"""Binance USDT-M Futures live adapter — REST API + UserData WebSocket.

Implements the ExecutionAdapter ABC for real trading on Binance Futures.
Used for both testnet and live modes (same API, different URLs/keys).

Security:
- HMAC-SHA256 request signing per Binance specification
- API keys only read from environment variables (never logged/persisted)
- Rate limit tracking with automatic backoff

Fill Notifications:
- Uses Binance UserData WebSocket stream (not polling)
- Listen key kept alive every 30 minutes
- Auto-reconnect with exponential backoff on disconnect
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets

from dashrock.adapters.base import (
    ExchangeError,
    ExecutionAdapter,
    FillCallback,
    InsufficientMarginError,
    OrderNotFoundError,
    RateLimitError,
)
from dashrock.config import Config
from dashrock.core.types import (
    Fill,
    LiveOrder,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

log = logging.getLogger(__name__)

# ─── Order type mapping ─────────────────────────────────────────

_ORDER_TYPE_MAP = {
    OrderType.MARKET: "MARKET",
    OrderType.STOP_MARKET: "STOP_MARKET",
    OrderType.TAKE_PROFIT_MARKET: "TAKE_PROFIT_MARKET",
    OrderType.TRAILING_STOP_MARKET: "TRAILING_STOP_MARKET",
    OrderType.LIMIT: "LIMIT",
}

_SIDE_MAP = {OrderSide.BUY: "BUY", OrderSide.SELL: "SELL"}

# Binance error codes that map to specific exceptions
_RETRYABLE_CODES = {-1021}  # Timestamp outside recvWindow
_ORDER_NOT_FOUND_CODES = {-2011}  # Unknown order sent
_MARGIN_ERROR_CODES = {-2010, -2019, -4003}  # Insufficient margin / qty too small


class BinanceLiveAdapter(ExecutionAdapter):
    """Binance USDT-M Futures execution adapter (live + testnet)."""

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str = "https://fapi.binance.com",
        ws_url: str = "wss://fstream.binance.com",
        cfg: Config,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._base_url = base_url
        self._ws_url = ws_url
        self._cfg = cfg
        self._client: httpx.AsyncClient | None = None
        self._fill_handler: FillCallback | None = None

        # Rate limit tracking
        self._used_weight = 0
        self._weight_limit = 2400

        # UserData WebSocket
        self._listen_key: str | None = None
        self._user_data_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._connected = asyncio.Event()

        # Position mode: True = hedge (dual side), False = one-way
        self._hedge_mode: bool = False

    # ─── Lifecycle ───────────────────────────────────────────

    async def start(self) -> None:
        """Connect HTTP client and start UserData WebSocket."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-MBX-APIKEY": self._api_key},
            timeout=15,
        )
        log.info(
            "Binance adapter started — base=%s mode=%s",
            self._base_url, self._cfg.mode,
        )

        # Start UserData stream for fill notifications
        await self._start_user_data_stream()

    async def stop(self) -> None:
        """Stop UserData WebSocket and close HTTP client."""
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self._user_data_task:
            self._user_data_task.cancel()
            self._user_data_task = None
        if self._listen_key and self._client:
            try:
                await self._client.delete(
                    "/fapi/v1/listenKey",
                    params=self._sign({}),
                )
            except Exception:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        log.info("Binance adapter stopped")

    def set_fill_handler(self, handler: FillCallback) -> None:
        self._fill_handler = handler

    # ─── Request Signing ─────────────────────────────────────

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add timestamp + HMAC-SHA256 signature to request params."""
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self._cfg.live.recv_window_ms
        query = urlencode(params)
        sig = hmac.new(self._api_secret, query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = True,
        weight: int = 1,
    ) -> Any:
        """Make an authenticated request with rate limit tracking and error handling."""
        assert self._client is not None, "Adapter not started"

        if params is None:
            params = {}
        if signed:
            params = self._sign(params)

        # Rate limit guard
        if self._used_weight > self._weight_limit * 0.95:
            raise RateLimitError(
                f"Rate limit near capacity: {self._used_weight}/{self._weight_limit}"
            )

        for attempt in range(self._cfg.live.max_retries):
            try:
                resp = await self._client.request(method, path, params=params)

                # Track rate limits from response headers
                weight_header = resp.headers.get("X-MBX-USED-WEIGHT-1M")
                if weight_header:
                    self._used_weight = int(weight_header)
                    if self._used_weight > self._weight_limit * 0.8:
                        log.warning(
                            "Binance rate limit: %d/%d used",
                            self._used_weight, self._weight_limit,
                        )

                # Handle HTTP-level errors
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", "60"))
                    log.error("Rate limited by Binance — waiting %ds", wait)
                    raise RateLimitError(f"HTTP 429 — retry after {wait}s")

                if resp.status_code == 418:
                    log.critical("IP BANNED by Binance! Immediate shutdown required.")
                    raise RateLimitError("IP BANNED (418)")

                data = resp.json()

                # Handle Binance API errors
                if resp.status_code >= 400:
                    code = data.get("code", 0)
                    msg = data.get("msg", "Unknown error")

                    if code in _ORDER_NOT_FOUND_CODES:
                        raise OrderNotFoundError(msg)
                    if code in _MARGIN_ERROR_CODES:
                        raise InsufficientMarginError(msg)
                    if code in _RETRYABLE_CODES and attempt < self._cfg.live.max_retries - 1:
                        log.warning(
                            "Retryable Binance error %d: %s (attempt %d)",
                            code, msg, attempt + 1,
                        )
                        await asyncio.sleep(self._cfg.live.retry_delay_sec)
                        params = self._sign({k: v for k, v in params.items()
                                             if k not in ("timestamp", "signature", "recvWindow")})
                        continue
                    raise ExchangeError(code, msg)

                return data

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < self._cfg.live.max_retries - 1:
                    log.warning("Network error: %s (attempt %d)", e, attempt + 1)
                    await asyncio.sleep(self._cfg.live.retry_delay_sec * (attempt + 1))
                    continue
                raise

        raise ExchangeError(0, "Max retries exceeded")

    # ─── ExecutionAdapter Interface ──────────────────────────

    async def place_order(self, intent: OrderIntent) -> LiveOrder:
        """Place an order on Binance Futures."""
        
        def _fmt(val: float) -> str:
            # Format float to string without scientific notation, max 8 decimals
            # Remove trailing zeros and trailing decimal point
            s = f"{val:.8f}".rstrip('0').rstrip('.')
            return s if s else "0"

        is_algo = intent.order_type in (
            OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET, OrderType.TRAILING_STOP_MARKET,
        )
        endpoint = "/fapi/v1/algoOrder" if is_algo else "/fapi/v1/order"

        params: dict[str, Any] = {
            "symbol": intent.symbol,
            "side": _SIDE_MAP[intent.side],
        }
        
        if is_algo:
            params["algoType"] = "CONDITIONAL"
            params["type"] = _ORDER_TYPE_MAP[intent.order_type]
            params["quantity"] = _fmt(intent.quantity)
            if intent.order_type == OrderType.TRAILING_STOP_MARKET:
                # Native trailing: callbackRate + optional activatePrice
                if intent.callback_rate is not None:
                    params["callbackRate"] = _fmt(intent.callback_rate)
                if intent.activate_price is not None:
                    params["activatePrice"] = _fmt(intent.activate_price)
            elif intent.stop_price:
                params["triggerPrice"] = _fmt(intent.stop_price)
        else:
            params["type"] = _ORDER_TYPE_MAP[intent.order_type]
            params["quantity"] = _fmt(intent.quantity)
            if intent.order_type != OrderType.MARKET and intent.stop_price:
                params["stopPrice"] = _fmt(intent.stop_price)

        # Hedge mode: use positionSide instead of reduceOnly
        if self._hedge_mode:
            if intent.reduce_only:
                # Closing: BUY closes SHORT, SELL closes LONG
                params["positionSide"] = "SHORT" if intent.side == OrderSide.BUY else "LONG"
            else:
                # Opening: BUY opens LONG, SELL opens SHORT
                params["positionSide"] = "LONG" if intent.side == OrderSide.BUY else "SHORT"
        elif intent.reduce_only:
            params["reduceOnly"] = "true"

        # Binance requires timeInForce for certain order types
        if intent.order_type == OrderType.LIMIT:
            params["timeInForce"] = "GTC"
            if intent.stop_price:
                params["price"] = _fmt(intent.stop_price)

        if intent.tag:
            if is_algo:
                params["clientAlgoId"] = intent.tag[:36]
            else:
                params["newClientOrderId"] = intent.tag[:36]  # Max 36 chars

        data = await self._request("POST", endpoint, params, weight=1)

        order = self._parse_order(data)

        log.info(
            "BINANCE %s ORDER: %s %s %s qty=%s stop=%s → id=%s status=%s",
            "ALGO" if is_algo else "STD", order.symbol, order.side.value, order.order_type.value,
            order.quantity, order.stop_price, order.order_id, order.status.value,
        )
        return order

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        """Cancel an order. Raises OrderNotFoundError if already gone."""
        params: dict[str, Any] = {"symbol": symbol}
        is_tag = not order_id.isdigit()

        # Try standard order cancellation first
        std_params = dict(params)
        if is_tag:
            std_params["origClientOrderId"] = order_id
        else:
            std_params["orderId"] = int(order_id)

        try:
            await self._request(
                "DELETE", "/fapi/v1/order",
                std_params, weight=1,
            )
            log.info("BINANCE CANCEL: %s order_id=%s", symbol, order_id)
            return
        except OrderNotFoundError:
            pass

        # If not found, it might be an algo order
        algo_params = dict(params)
        if is_tag:
            algo_params["clientAlgoId"] = order_id
        else:
            algo_params["algoId"] = int(order_id)

        await self._request(
            "DELETE", "/fapi/v1/algoOrder",
            algo_params, weight=1,
        )
        log.info("BINANCE CANCEL ALGO: %s order_id=%s", symbol, order_id)

    async def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all open orders for a symbol (single API call)."""
        count = 0
        try:
            await self._request(
                "DELETE", "/fapi/v1/allOpenOrders",
                {"symbol": symbol}, weight=1,
            )
            count += 1
        except ExchangeError:
            pass

        try:
            await self._request(
                "DELETE", "/fapi/v1/algoOpenOrders",
                {"symbol": symbol}, weight=1,
            )
            count += 1
        except ExchangeError:
            pass

        if count > 0:
            log.info("BINANCE CANCEL ALL (Std+Algo): %s", symbol)
            return -1
        return 0

    async def get_open_orders(self, symbol: str) -> list[LiveOrder]:
        """Return all open orders for a symbol."""
        orders = []
        try:
            data = await self._request(
                "GET", "/fapi/v1/openOrders",
                {"symbol": symbol}, weight=1,
            )
            orders.extend([self._parse_order(o) for o in data])
        except ExchangeError:
            pass
            
        try:
            algo_data = await self._request(
                "GET", "/fapi/v1/openAlgoOrders",
                {"symbol": symbol}, weight=1,
            )
            orders.extend([self._parse_order(o) for o in algo_data])
        except ExchangeError:
            pass
            
        return orders

    async def get_all_open_orders(self) -> list[LiveOrder]:
        """Return all open standard and algo orders for the entire account."""
        orders = []
        try:
            data = await self._request(
                "GET", "/fapi/v1/openOrders",
                weight=40,
            )
            orders.extend([self._parse_order(o) for o in data])
        except ExchangeError:
            pass
            
        try:
            algo_data = await self._request(
                "GET", "/fapi/v1/openAlgoOrders",
                weight=40,
            )
            orders.extend([self._parse_order(o) for o in algo_data])
        except ExchangeError:
            pass
            
        return orders

    async def get_position(self, symbol: str) -> Position:
        """Return the current position for a symbol.

        In Hedge Mode, Binance returns two entries per symbol (LONG + SHORT).
        We check all entries and return the first with non-zero quantity.
        """
        data = await self._request(
            "GET", "/fapi/v2/positionRisk",
            {"symbol": symbol},
            weight=5,
        )
        for p in data:
            if p["symbol"] == symbol:
                qty = abs(float(p["positionAmt"]))
                if qty == 0:
                    continue  # Check other side (Hedge Mode has LONG + SHORT)
                side = OrderSide.BUY if float(p["positionAmt"]) > 0 else OrderSide.SELL
                return Position(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    entry_price=float(p["entryPrice"]),
                    opened_at_ms=int(p.get("updateTime", 0)),
                )
        # All sides are flat
        return Position(
            symbol=symbol, side=None, quantity=0,
            entry_price=0, opened_at_ms=0,
        )

    async def get_equity_usd(self) -> float:
        """Return total account equity in USDT."""
        data = await self._request("GET", "/fapi/v2/balance", weight=5)
        for asset in data:
            if asset["asset"] == "USDT":
                return float(asset["balance"])
        return 0.0

    async def get_funding_rate(self, symbol: str) -> float:
        """Return the current funding rate for a symbol."""
        data = await self._request(
            "GET", "/fapi/v1/premiumIndex",
            {"symbol": symbol},
            signed=False, weight=1,
        )
        return float(data.get("lastFundingRate", 0))

    # ─── Exchange Configuration ──────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """Set leverage for a symbol."""
        await self._request(
            "POST", "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": leverage},
            weight=1,
        )
        log.info("Set leverage %dx for %s", leverage, symbol)

    async def set_margin_type(self, symbol: str, margin_type: str) -> None:
        """Set margin type (ISOLATED or CROSSED) for a symbol."""
        try:
            await self._request(
                "POST", "/fapi/v1/marginType",
                {"symbol": symbol, "marginType": margin_type},
                weight=1,
            )
            log.info("Set margin type %s for %s", margin_type, symbol)
        except ExchangeError as e:
            # -4046 = "No need to change margin type" (already set)
            if e.code == -4046:
                log.debug("Margin type already %s for %s", margin_type, symbol)
            else:
                raise

    async def get_position_mode(self) -> bool:
        """Return True if hedge mode (dual position side), False if one-way.

        Uses GET /fapi/v1/positionSide/dual.
        """
        data = await self._request(
            "GET", "/fapi/v1/positionSide/dual",
            weight=30,
        )
        return data.get("dualSidePosition", False)

    async def set_position_mode(self, hedge: bool) -> None:
        """Switch between one-way mode and hedge mode.

        Uses POST /fapi/v1/positionSide/dual.

        NOTE: Binance will reject this if there are any open positions or orders.
              This is a global setting — it applies to ALL USDT-M symbols.
        """
        await self._request(
            "POST", "/fapi/v1/positionSide/dual",
            {"dualSidePosition": "true" if hedge else "false"},
            weight=1,
        )
        mode_str = "HEDGE" if hedge else "ONE-WAY"
        self._hedge_mode = hedge  # sync cached state for order placement
        log.info("Position mode set to %s", mode_str)

    # ─── UserData WebSocket ──────────────────────────────────

    async def _start_user_data_stream(self) -> None:
        """Create listen key and start UserData WebSocket + keepalive."""
        assert self._client is not None
        resp = await self._client.post("/fapi/v1/listenKey")
        data = resp.json()
        self._listen_key = data["listenKey"]
        log.info("UserData listen key obtained")

        self._user_data_task = asyncio.create_task(
            self._user_data_loop(), name="user-data-ws",
        )
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(), name="listen-key-keepalive",
        )

    async def _user_data_loop(self) -> None:
        """Connect to UserData WebSocket and process fill events."""
        backoff = 1
        while True:
            try:
                url = f"{self._ws_url}/ws/{self._listen_key}"
                async with websockets.connect(
                    url, ping_interval=30, ping_timeout=20, open_timeout=30,
                ) as ws:
                    log.info("UserData WebSocket connected")
                    self._connected.set()
                    backoff = 1

                    async for raw_msg in ws:
                        try:
                            import json
                            msg = json.loads(raw_msg)
                            event_type = msg.get("e")

                            if event_type == "ORDER_TRADE_UPDATE":
                                await self._handle_order_update(msg)
                            elif event_type == "ACCOUNT_UPDATE":
                                log.debug("Account update: %s", msg)
                            elif event_type == "listenKeyExpired":
                                log.warning("Listen key expired, reconnecting...")
                                break  # Will reconnect
                        except Exception:
                            log.warning("Error processing UserData message", exc_info=True)

            except asyncio.CancelledError:
                return
            except Exception:
                self._connected.clear()
                log.warning(
                    "UserData WS disconnected, reconnecting in %ds...", backoff,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

                # Refresh listen key on reconnect
                try:
                    assert self._client is not None
                    resp = await self._client.post("/fapi/v1/listenKey")
                    data = resp.json()
                    self._listen_key = data["listenKey"]
                except Exception:
                    log.warning("Failed to refresh listen key", exc_info=True)

    async def _keepalive_loop(self) -> None:
        """Refresh listen key every N seconds to prevent expiry."""
        interval = self._cfg.live.listen_key_refresh_sec
        try:
            while True:
                await asyncio.sleep(interval)
                if self._client:
                    try:
                        await self._client.put("/fapi/v1/listenKey")
                        log.debug("Listen key refreshed")
                    except Exception:
                        log.warning("Failed to refresh listen key", exc_info=True)
        except asyncio.CancelledError:
            pass

    async def _handle_order_update(self, msg: dict) -> None:
        """Convert Binance ORDER_TRADE_UPDATE to a Fill and invoke callback.

        IMPORTANT: We only process FILLED (fully filled) events.
        PARTIALLY_FILLED events are logged but ignored — this prevents
        duplicate SL/TP orders from being placed for each partial fill.
        Binance provides the correct average price (ap) and cumulative
        quantity (z) in the final FILLED event.
        """
        order_data = msg.get("o", {})
        status = order_data.get("X", "")

        # Only process fully filled orders
        if status == "PARTIALLY_FILLED":
            log.debug(
                "Partial fill for %s order %s — qty=%.8g, waiting for FILLED",
                order_data.get("s"), order_data.get("i"), float(order_data.get("l", 0)),
            )
            return
        if status != "FILLED":
            return

        fill = Fill(
            order_id=str(order_data["i"]),  # orderId
            symbol=order_data["s"],  # symbol
            side=OrderSide(order_data["S"]),  # side
            price=float(order_data["ap"]),  # average price (VWAP across all partials)
            quantity=float(order_data["z"]),  # cumulative filled qty (total position)
            fee=float(order_data.get("n", 0)),  # commission (last fill's fee)
            timestamp_ms=int(msg.get("T", time.time() * 1000)),  # transaction time
            tag=order_data.get("c", ""),  # clientOrderId
        )

        log.info(
            "BINANCE FILL: %s %s @ %.8g qty=%.8g fee=%.6f (order %s)",
            fill.symbol, fill.side.value, fill.price,
            fill.quantity, fill.fee, fill.order_id,
        )

        if self._fill_handler:
            try:
                await self._fill_handler(fill)
            except Exception:
                log.error("Error in fill handler", exc_info=True)

    # ─── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _parse_order(data: dict) -> LiveOrder:
        """Parse a Binance standard or algo order response into a LiveOrder."""
        is_algo = "algoId" in data
        return LiveOrder(
            order_id=str(data.get("algoId") or data["orderId"]),
            symbol=data["symbol"],
            side=OrderSide(data["side"]),
            order_type=OrderType(data.get("orderType") or data["type"]),
            stop_price=float(data.get("triggerPrice") or data.get("stopPrice", 0)) or None,
            quantity=float(data.get("quantity") if is_algo else data["origQty"]),
            status=OrderStatus(data.get("algoStatus") or data["status"]),
            reduce_only=data.get("reduceOnly", False),
            tag=data.get("clientAlgoId") or data.get("clientOrderId", ""),
        )
