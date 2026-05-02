"""Tests for BinanceLiveAdapter — mocked HTTP transport.

Tests cover:
- HMAC-SHA256 request signing
- Order placement/cancellation (correct Binance params)
- Error code → exception mapping
- Fill parsing from UserData WebSocket messages
- Position and equity parsing
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from dashrock.adapters.base import (
    ExchangeError,
    InsufficientMarginError,
    OrderNotFoundError,
    RateLimitError,
)
from dashrock.adapters.binance_live import BinanceLiveAdapter
from dashrock.config import Config, load_config
from dashrock.core.types import (
    Fill,
    LiveOrder,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def cfg():
    """Minimal config for live adapter tests."""
    from pathlib import Path
    return load_config(Path("config.yaml"))


@pytest.fixture
def adapter(cfg):
    """Create adapter without starting it (no network)."""
    a = BinanceLiveAdapter(
        api_key="test_api_key",
        api_secret="test_api_secret",
        base_url="https://fapi.binance.com",
        ws_url="wss://fstream.binance.com",
        cfg=cfg,
    )
    return a


# ─── Signing Tests ───────────────────────────────────────────────


def test_sign_request(adapter):
    """HMAC-SHA256 signature should match expected output."""
    params = {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.001"}
    signed = adapter._sign(params)

    assert "timestamp" in signed
    assert "signature" in signed
    assert "recvWindow" in signed

    # Verify signature is a valid hex string
    assert len(signed["signature"]) == 64
    int(signed["signature"], 16)  # Should not raise

    # Verify signature was computed correctly
    sig_params = {k: v for k, v in signed.items() if k != "signature"}
    from urllib.parse import urlencode
    query = urlencode(sig_params)
    expected_sig = hmac.new(
        b"test_api_secret", query.encode(), hashlib.sha256,
    ).hexdigest()
    assert signed["signature"] == expected_sig


def test_sign_includes_recv_window(adapter):
    """recvWindow should be set from config."""
    signed = adapter._sign({})
    assert signed["recvWindow"] == adapter._cfg.live.recv_window_ms


# ─── Order Parsing Tests ────────────────────────────────────────


def test_parse_order():
    """Binance order response should map correctly to LiveOrder."""
    data = {
        "orderId": 12345,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "STOP_MARKET",
        "stopPrice": "50000.00",
        "origQty": "0.001",
        "status": "NEW",
        "reduceOnly": True,
        "clientOrderId": "sl",
    }
    order = BinanceLiveAdapter._parse_order(data)
    assert isinstance(order, LiveOrder)
    assert order.order_id == "12345"
    assert order.symbol == "BTCUSDT"
    assert order.side == OrderSide.BUY
    assert order.order_type == OrderType.STOP_MARKET
    assert order.stop_price == 50000.0
    assert order.quantity == 0.001
    assert order.status == OrderStatus.NEW
    assert order.reduce_only is True
    assert order.tag == "sl"


# ─── Fill Parsing Tests ─────────────────────────────────────────


async def test_fill_parsing(adapter):
    """ORDER_TRADE_UPDATE message should be parsed into a Fill and invoke callback."""
    fill_received = []
    adapter._fill_handler = AsyncMock(side_effect=lambda f: fill_received.append(f))

    msg = {
        "e": "ORDER_TRADE_UPDATE",
        "T": 1700000000000,
        "o": {
            "i": 99999,  # orderId
            "s": "ETHUSDT",  # symbol
            "S": "SELL",  # side
            "ap": "2500.50",  # average price
            "z": "0.5",  # cumulative filled qty
            "l": "0.5",  # last filled qty
            "n": "0.05",  # commission
            "c": "test_tag",  # clientOrderId
            "X": "FILLED",  # status
        },
    }

    await adapter._handle_order_update(msg)

    assert len(fill_received) == 1
    fill = fill_received[0]
    assert fill.order_id == "99999"
    assert fill.symbol == "ETHUSDT"
    assert fill.side == OrderSide.SELL
    assert fill.price == 2500.50
    assert fill.quantity == 0.5
    assert fill.fee == 0.05
    assert fill.timestamp_ms == 1700000000000


async def test_fill_ignores_non_fill_status(adapter):
    """ORDER_TRADE_UPDATE with non-fill status should be ignored."""
    adapter._fill_handler = AsyncMock()

    msg = {
        "e": "ORDER_TRADE_UPDATE",
        "T": 1700000000000,
        "o": {"i": 1, "s": "BTCUSDT", "S": "BUY", "ap": "0", "l": "0", "n": "0", "X": "NEW"},
    }

    await adapter._handle_order_update(msg)
    adapter._fill_handler.assert_not_called()


# ─── Error Handling Tests ────────────────────────────────────────


async def test_request_order_not_found(adapter):
    """Binance error -2011 should raise OrderNotFoundError."""
    import httpx

    mock_response = httpx.Response(
        status_code=400,
        json={"code": -2011, "msg": "Unknown order sent."},
        request=httpx.Request("DELETE", "https://fapi.binance.com/fapi/v1/order"),
    )
    mock_response.headers["X-MBX-USED-WEIGHT-1M"] = "10"

    adapter._client = AsyncMock()
    adapter._client.request = AsyncMock(return_value=mock_response)

    with pytest.raises(OrderNotFoundError):
        await adapter._request("DELETE", "/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": 1})


async def test_request_insufficient_margin(adapter):
    """Binance error -2010 should raise InsufficientMarginError."""
    import httpx

    mock_response = httpx.Response(
        status_code=400,
        json={"code": -2010, "msg": "Account has insufficient balance for requested action."},
        request=httpx.Request("POST", "https://fapi.binance.com/fapi/v1/order"),
    )
    mock_response.headers["X-MBX-USED-WEIGHT-1M"] = "10"

    adapter._client = AsyncMock()
    adapter._client.request = AsyncMock(return_value=mock_response)

    with pytest.raises(InsufficientMarginError):
        await adapter._request("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})


async def test_request_rate_limit_guard(adapter):
    """Should raise RateLimitError when near rate limit capacity."""
    adapter._used_weight = 2300  # 95.8% of 2400 limit
    adapter._client = AsyncMock()

    with pytest.raises(RateLimitError):
        await adapter._request("GET", "/fapi/v1/openOrders", {"symbol": "BTCUSDT"})


async def test_request_generic_exchange_error(adapter):
    """Unknown Binance error codes should raise ExchangeError."""
    import httpx

    mock_response = httpx.Response(
        status_code=400,
        json={"code": -9999, "msg": "Some unknown error."},
        request=httpx.Request("POST", "https://fapi.binance.com/fapi/v1/order"),
    )
    mock_response.headers["X-MBX-USED-WEIGHT-1M"] = "10"

    adapter._client = AsyncMock()
    adapter._client.request = AsyncMock(return_value=mock_response)

    with pytest.raises(ExchangeError) as exc_info:
        await adapter._request("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})
    assert exc_info.value.code == -9999


# ─── Lifecycle Tests ─────────────────────────────────────────────


def test_adapter_initial_state(adapter):
    """Adapter should be in clean state before start."""
    assert adapter._client is None
    assert adapter._listen_key is None
    assert adapter._fill_handler is None
    assert adapter._used_weight == 0


def test_set_fill_handler(adapter):
    """set_fill_handler should store the callback."""
    handler = AsyncMock()
    adapter.set_fill_handler(handler)
    assert adapter._fill_handler is handler


# ─── Safe Cancel Integration Test ────────────────────────────────


async def test_safe_cancel_with_order_not_found():
    """ExecutionManager._safe_cancel should return True on OrderNotFoundError."""
    from dashrock.execution.manager import ExecutionManager
    from dashrock.core.events import EventBus

    adapter = AsyncMock()
    adapter.cancel_order = AsyncMock(side_effect=OrderNotFoundError("gone"))

    repo = AsyncMock()
    repo.update_order_status = AsyncMock()

    bus = EventBus()

    from dashrock.market.symbol_registry import SymbolRegistry
    from pathlib import Path
    cfg = load_config(Path("config.yaml"))

    mgr = ExecutionManager(
        adapter=adapter, config=cfg, repo=repo,
        bus=bus, registry=SymbolRegistry(),
    )

    result = await mgr._safe_cancel("BTCUSDT", "order-123")
    assert result is True
    repo.update_order_status.assert_called_with("order-123", "CANCELED")
