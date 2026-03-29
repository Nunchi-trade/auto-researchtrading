import pytest
import os
import tempfile
import time
from unittest.mock import AsyncMock
from monitoring.watchdog import Watchdog
from config.settings import Settings
from exchange.types import Order, OrderSide, OrderType, OrderStatus


@pytest.fixture
def settings():
    fd, path = tempfile.mkstemp(suffix=".heartbeat")
    os.close(fd)
    s = Settings(
        WATCHDOG_INTERVAL_SECONDS=1,
        WATCHDOG_HEARTBEAT_PATH=path,
    )
    yield s
    if os.path.exists(path):
        os.unlink(path)


class TestWatchdog:
    def test_is_alive_fresh(self, settings):
        client = AsyncMock()
        wd = Watchdog(settings, client)
        with open(settings.WATCHDOG_HEARTBEAT_PATH, "w") as f:
            f.write(str(int(time.time() * 1000)))
        assert wd.is_alive() is True

    def test_is_alive_stale(self, settings):
        client = AsyncMock()
        wd = Watchdog(settings, client)
        stale_time = time.time() - settings.WATCHDOG_INTERVAL_SECONDS * 4
        with open(settings.WATCHDOG_HEARTBEAT_PATH, "w") as f:
            f.write("0")
        os.utime(settings.WATCHDOG_HEARTBEAT_PATH, (stale_time, stale_time))
        assert wd.is_alive() is False

    def test_is_alive_no_file(self, settings):
        client = AsyncMock()
        wd = Watchdog(settings, client)
        if os.path.exists(settings.WATCHDOG_HEARTBEAT_PATH):
            os.unlink(settings.WATCHDOG_HEARTBEAT_PATH)
        assert wd.is_alive() is False

    @pytest.mark.asyncio
    async def test_startup_cleanup_no_orders(self, settings):
        client = AsyncMock()
        client.get_open_orders = AsyncMock(return_value=[])
        client.cancel_order = AsyncMock()
        wd = Watchdog(settings, client)
        await wd.startup_cleanup()
        assert client.get_open_orders.called
        assert not client.cancel_order.called

    @pytest.mark.asyncio
    async def test_startup_cleanup_preserves_trigger_orders(self, settings):
        market_order = Order(
            id="mkt-1",
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=0.1,
            price=50000.0,
            status=OrderStatus.PENDING,
            filled_size=0.0,
            avg_fill_price=0.0,
        )
        trigger_order = Order(
            id="stop-1",
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.TRIGGER,
            size=0.1,
            price=49000.0,
            status=OrderStatus.PENDING,
            filled_size=0.0,
            avg_fill_price=0.0,
        )
        client = AsyncMock()
        client.get_open_orders = AsyncMock(return_value=[market_order, trigger_order])
        client.cancel_order = AsyncMock(return_value=True)
        wd = Watchdog(settings, client)
        await wd.startup_cleanup()
        assert client.cancel_order.call_count == 1
        client.cancel_order.assert_called_once_with("BTC", "mkt-1")
