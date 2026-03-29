import pytest
from unittest.mock import AsyncMock
from exchange.stop_manager import StopManager
from exchange.types import Order, OrderSide, OrderType, OrderStatus
from config.settings import Settings


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
        order = await sm.place_stop("BTC", OrderSide.SELL, 0.1, 49000.0)
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
