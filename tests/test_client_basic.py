"""Тесты Client class — auth, handler-регистрация, event-dispatch.

Запуск:
    cd sdks/python
    pip install -e .[dev]
    pytest tests/
"""

import asyncio
import json

import pytest

from zonetrade_sdk import Client, Bar, TrapFlipSignal
from zonetrade_sdk.client import _model_for_channel
from zonetrade_sdk.exceptions import AuthError


def test_client_requires_api_key():
    with pytest.raises(AuthError):
        Client(api_key="")


def test_handler_registration():
    client = Client(api_key="zt_test")
    received = []

    @client.on("bar")
    async def handler(bar):
        received.append(bar)

    assert "bar" in client._handlers
    assert len(client._handlers["bar"]) == 1


def test_model_for_channel():
    assert _model_for_channel("bar.1m.BTCUSDT") is Bar
    assert _model_for_channel("signal.trap-flip.ETHUSDT") is TrapFlipSignal
    assert _model_for_channel("unknown.channel") is None


@pytest.mark.asyncio
async def test_dispatch_calls_handler():
    client = Client(api_key="zt_test")
    received = []

    @client.on("bar")
    async def handler(bar):
        received.append(bar)

    # Simulate incoming message.
    raw = json.dumps({
        "event": "bar",
        "channel": "bar.1m.BTCUSDT",
        "data": {
            "symbol": "BTCUSDT",
            "tf": "1m",
            "time": 1778524800,
            "open": 81000,
            "high": 81120,
            "low": 80950,
            "close": 81080,
            "volume": 12.34,
        },
    })
    await client._handle_message(raw)

    assert len(received) == 1
    assert isinstance(received[0], Bar)
    assert received[0].symbol == "BTCUSDT"
    assert received[0].close == 81080


@pytest.mark.asyncio
async def test_dispatch_channel_specific_handler():
    client = Client(api_key="zt_test")
    btc_only = []

    @client.on("bar.1m.BTCUSDT")
    async def btc_handler(bar):
        btc_only.append(bar)

    # BTC event → handler called
    btc_msg = json.dumps({
        "event": "bar",
        "channel": "bar.1m.BTCUSDT",
        "data": {"symbol": "BTCUSDT", "tf": "1m", "time": 0,
                 "open": 1, "high": 2, "low": 0, "close": 1.5, "volume": 100},
    })
    await client._handle_message(btc_msg)
    assert len(btc_only) == 1

    # ETH event → handler НЕ called
    eth_msg = json.dumps({
        "event": "bar",
        "channel": "bar.1m.ETHUSDT",
        "data": {"symbol": "ETHUSDT", "tf": "1m", "time": 0,
                 "open": 1, "high": 2, "low": 0, "close": 1.5, "volume": 100},
    })
    await client._handle_message(eth_msg)
    assert len(btc_only) == 1  # не вырос


@pytest.mark.asyncio
async def test_bad_json_no_crash():
    client = Client(api_key="zt_test")
    # Не должно бросить — logger.warning + continue
    await client._handle_message("not json {")


@pytest.mark.asyncio
async def test_dispatch_hello():
    client = Client(api_key="zt_test")
    received = []

    @client.on("hello")
    async def on_hello(msg):
        received.append(msg)

    msg = json.dumps({"event": "hello", "userId": 13, "settings": {"subscriptionTier": "pro"}})
    await client._handle_message(msg)
    assert len(received) == 1
    assert received[0]["userId"] == 13
