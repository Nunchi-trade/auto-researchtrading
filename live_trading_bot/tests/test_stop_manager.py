import pytest
from datetime import datetime
from unittest.mock import AsyncMock
from live_trading_bot.exchange.stop_manager import StopManager
from live_trading_bot.exchange.types import (
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    Position,
    PositionSide,
)
from live_trading_bot.config.settings import Settings


@pytest.fixture
def settings():
    return Settings(STOP_WIDENING_MULT=1.5)


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.place_trigger_order = AsyncMock(
        return_value=Order(
            id="stop-1",
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.TRIGGER,
            size=0.1,
            price=49000.0,
            status=OrderStatus.PENDING,
            filled_size=0.0,
            avg_fill_price=49000.0,
        )
    )
    client.cancel_order = AsyncMock(return_value=True)
    return client


class TestStopManager:
    @pytest.mark.asyncio
    async def test_place_stop_calls_trigger_order(self, settings, mock_client):
        sm = StopManager(mock_client, settings)
        await sm.place_stop("BTC", OrderSide.SELL, 0.1, 49000.0)
        assert mock_client.place_trigger_order.called
        assert sm.get_stop("BTC") is not None

    @pytest.mark.asyncio
    async def test_place_stop_replaces_existing(self, settings, mock_client):
        sm = StopManager(mock_client, settings)
        await sm.place_stop("BTC", OrderSide.SELL, 0.1, 49000.0)
        await sm.place_stop("BTC", OrderSide.SELL, 0.1, 48500.0)
        assert mock_client.cancel_order.called
        assert mock_client.place_trigger_order.call_count == 2

    @pytest.mark.asyncio
    async def test_cancel_stop_removes_tracking(self, settings, mock_client):
        sm = StopManager(mock_client, settings)
        await sm.place_stop("BTC", OrderSide.SELL, 0.1, 49000.0)
        await sm.cancel_stop("BTC")
        assert sm.get_stop("BTC") is None

    @pytest.mark.asyncio
    async def test_cancel_stop_idempotent(self, settings, mock_client):
        sm = StopManager(mock_client, settings)
        result = await sm.cancel_stop("BTC")
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_all_stops(self, settings, mock_client):
        sm = StopManager(mock_client, settings)
        await sm.place_stop("BTC", OrderSide.SELL, 0.1, 49000.0)
        await sm.place_stop("ETH", OrderSide.SELL, 1.0, 1900.0)
        await sm.cancel_all_stops()
        assert sm.get_stop("BTC") is None
        assert sm.get_stop("ETH") is None


def _make_trigger_order(symbol, oid, price, ts=None):
    return Order(
        id=oid,
        symbol=symbol,
        side=OrderSide.SELL,
        order_type=OrderType.TRIGGER,
        size=0.1,
        price=price,
        status=OrderStatus.PENDING,
        timestamp=ts or datetime(2026, 1, 1),
    )


def _make_limit_order(symbol, oid):
    return Order(
        id=oid,
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=0.1,
        price=50000.0,
        status=OrderStatus.PENDING,
    )


class TestLoadExistingStops:
    @pytest.mark.asyncio
    async def test_populates_stops_from_trigger_orders(self, settings, mock_client):
        """Trigger orders for symbols with positions are loaded into _stops."""
        mock_client.get_open_orders = AsyncMock(
            return_value=[
                _make_trigger_order("BTC", "s1", 49000.0),
                _make_trigger_order("ETH", "s2", 1900.0),
            ]
        )
        sm = StopManager(mock_client, settings)
        loaded = await sm.load_existing_stops({"BTC", "ETH"})
        assert loaded == 2
        btc_stop = sm.get_stop("BTC")
        assert btc_stop is not None
        assert btc_stop.id == "s1"
        eth_stop = sm.get_stop("ETH")
        assert eth_stop is not None
        assert eth_stop.id == "s2"

    @pytest.mark.asyncio
    async def test_ignores_non_trigger_orders(self, settings, mock_client):
        """Limit orders are not loaded into _stops."""
        mock_client.get_open_orders = AsyncMock(
            return_value=[
                _make_limit_order("BTC", "lim1"),
                _make_trigger_order("BTC", "s1", 49000.0),
            ]
        )
        sm = StopManager(mock_client, settings)
        loaded = await sm.load_existing_stops({"BTC"})
        assert loaded == 1
        stop = sm.get_stop("BTC")
        assert stop is not None
        assert stop.id == "s1"

    @pytest.mark.asyncio
    async def test_ignores_symbols_without_positions(self, settings, mock_client):
        """Trigger orders for symbols we don't hold are not loaded."""
        mock_client.get_open_orders = AsyncMock(
            return_value=[_make_trigger_order("SOL", "s1", 20.0)]
        )
        sm = StopManager(mock_client, settings)
        loaded = await sm.load_existing_stops({"BTC"})
        assert loaded == 0
        assert sm.get_stop("SOL") is None

    @pytest.mark.asyncio
    async def test_deduplicates_keeping_newest(self, settings, mock_client):
        """When multiple trigger orders exist for one symbol, keep the newest and cancel the rest."""
        mock_client.get_open_orders = AsyncMock(
            return_value=[
                _make_trigger_order("BTC", "old", 48000.0, datetime(2026, 1, 1)),
                _make_trigger_order("BTC", "new", 49000.0, datetime(2026, 1, 2)),
            ]
        )
        sm = StopManager(mock_client, settings)
        loaded = await sm.load_existing_stops({"BTC"})
        assert loaded == 1
        stop = sm.get_stop("BTC")
        assert stop is not None
        assert stop.id == "new"
        mock_client.cancel_order.assert_called_once_with("BTC", "old")

    @pytest.mark.asyncio
    async def test_empty_exchange(self, settings, mock_client):
        """No orders on the exchange — _stops stays empty, no errors."""
        mock_client.get_open_orders = AsyncMock(return_value=[])
        sm = StopManager(mock_client, settings)
        loaded = await sm.load_existing_stops({"BTC"})
        assert loaded == 0

    @pytest.mark.asyncio
    async def test_restart_cycle_no_duplicate_placement(self, settings, mock_client):
        """After loading existing stops, refresh_stops skips placement if price is close."""
        existing_stop = _make_trigger_order("BTC", "s1", 49000.0)
        mock_client.get_open_orders = AsyncMock(return_value=[existing_stop])

        sm = StopManager(mock_client, settings)
        await sm.load_existing_stops({"BTC"})

        # refresh_stops with a position whose calculated stop is close to 49000
        pos = Position(
            symbol="BTC",
            side=PositionSide.LONG,
            size=0.1,
            entry_price=50000.0,
            current_price=50000.0,
            unrealized_pnl=0.0,
        )
        # ATR=100, mult=8.0, widening=1.5 → distance=1200 → stop=48800
        # |49000-48800|/48800 = 0.004 < 0.01 → skip
        atrs = {"BTC": 100.0}
        await sm.refresh_stops({"BTC": pos}, atrs)
        assert mock_client.place_trigger_order.call_count == 0
