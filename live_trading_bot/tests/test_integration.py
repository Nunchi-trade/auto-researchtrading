"""Integration tests: ExecutionEngine + SignalState + StopManager + Watchdog."""

import time

import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from exchange.stop_manager import StopManager
from exchange.types import (
    AccountState,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
)
from execution.execution_engine import ExecutionEngine
from execution.signal_state import SignalState
from monitoring.watchdog import Watchdog


def _make_filled_order(
    symbol="BTC",
    side=OrderSide.BUY,
    size=0.1,
    price=50000.0,
    order_type=OrderType.MARKET,
):
    return Order(
        id="test-order-1",
        symbol=symbol,
        side=side,
        order_type=order_type,
        size=size,
        price=price,
        status=OrderStatus.FILLED,
        filled_size=size,
        avg_fill_price=price,
    )


def _make_pending_trigger_order(
    symbol="BTC", side=OrderSide.SELL, size=0.1, price=49925.0
):
    return Order(
        id="stop-order-1",
        symbol=symbol,
        side=side,
        order_type=OrderType.TRIGGER,
        size=size,
        price=price,
        status=OrderStatus.PENDING,
        filled_size=0.0,
        avg_fill_price=0.0,
    )


@pytest.fixture
def settings():
    return Settings(
        TICK_EXECUTION_ENABLED=True,
        ENTRY_SLIPPAGE_PCT=0.02,
        EXECUTION_COOLDOWN_MS=100,
        EMERGENCY_EXIT_PCT=0.10,
        STOP_WIDENING_MULT=1.5,
        WATCHDOG_INTERVAL_SECONDS=30,
        WATCHDOG_HEARTBEAT_PATH="/tmp/test_integration_heartbeat",
    )


@pytest.fixture
def signal_state():
    return SignalState()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.place_order = AsyncMock(return_value=_make_filled_order())

    def _mock_trigger_order(symbol, side, size, trigger_price, **kwargs):
        return _make_pending_trigger_order(
            symbol=symbol, side=side, size=size, price=trigger_price
        )

    client.place_trigger_order = AsyncMock(side_effect=_mock_trigger_order)
    client.cancel_order = AsyncMock(return_value=True)
    client.cancel_all_orders = AsyncMock(return_value=True)
    # HyperliquidClient no longer has dry_run — mode is determined by Exchange type
    return client


@pytest.mark.asyncio
async def test_full_tick_execution_cycle(settings, signal_state, mock_client):
    """Signal → entry → peak update → ATR trailing stop → close → cleanup.

    1. Signal (long BTC, $5000 notional, ATR=50, entry=50000)
    2. Tick at entry → enter 0.1 BTC
    3. StopManager places exchange-side stop
    4. Price rises to 51000 → peak updated
    5. Price drops to 50500 → ATR stop (51000 - 8×50 = 50600) → close
    6. on_position_closed cancels exchange stop
    7. SignalState cleared after close
    """
    engine = ExecutionEngine(signal_state, mock_client, settings, ["BTC"])
    stop_manager = StopManager(mock_client, settings)

    async def on_closed(symbol: str):
        await stop_manager.cancel_stop(symbol)

    engine.on_position_closed = on_closed

    signal_state.update_signal("BTC", 5000.0, 50.0, 50000.0, None)
    assert signal_state.get_direction("BTC") == 1
    assert signal_state.get_target("BTC") == 5000.0

    entry_order = await engine.on_tick("BTC", 50000.0)
    assert entry_order is not None
    assert entry_order.status == OrderStatus.FILLED
    assert engine._position_sizes["BTC"] == pytest.approx(0.1, abs=1e-4)
    assert engine._entry_prices["BTC"] == 50000.0
    assert engine._last_executed_direction["BTC"] == 1

    await stop_manager.place_stop("BTC", OrderSide.SELL, 0.1, 49925.0)
    assert stop_manager.get_stop("BTC") is not None

    # peak/trough updates before cooldown gate, so 51000 peak is recorded
    _ = await engine.on_tick("BTC", 51000.0)
    assert signal_state.peak_prices["BTC"] == 51000.0

    time.sleep(0.15)

    # ATR trailing stop: peak=51000, stop=51000 - 8.0×50 = 50600, price=50500 < 50600
    close_order = await engine.on_tick("BTC", 50500.0)
    assert close_order is not None
    assert close_order.status == OrderStatus.FILLED

    assert stop_manager.get_stop("BTC") is None

    assert signal_state.get_target("BTC") == 0.0
    assert signal_state.get_direction("BTC") == 0
    assert "BTC" not in signal_state.signal_atr
    assert "BTC" not in signal_state.signal_entry
    assert "BTC" not in signal_state.peak_prices

    assert engine._position_sizes["BTC"] == 0.0
    assert engine._entry_prices["BTC"] == 0.0
    assert engine._last_executed_direction["BTC"] == 0


@pytest.mark.asyncio
async def test_bar_close_fallback_no_tick_execution(signal_state, mock_client):
    """Signals sit in SignalState when TICK_EXECUTION_ENABLED=False (no engine)."""

    Settings(
        TICK_EXECUTION_ENABLED=False,
        ENTRY_SLIPPAGE_PCT=0.02,
        EXECUTION_COOLDOWN_MS=100,
        EMERGENCY_EXIT_PCT=0.10,
        STOP_WIDENING_MULT=1.5,
    )

    signal_state.update_signal("BTC", 5000.0, 50.0, 50000.0, None)

    assert signal_state.get_target("BTC") == 5000.0
    assert signal_state.get_direction("BTC") == 1
    assert signal_state.signal_atr["BTC"] == 50.0
    assert signal_state.signal_entry["BTC"] == 50000.0

    signal_state.update_peak_trough("BTC", 50500.0)
    assert signal_state.peak_prices["BTC"] == 50500.0

    signal_state.update_peak_trough("BTC", 49500.0)
    assert signal_state.trough_prices["BTC"] == 49500.0

    assert mock_client.place_order.call_count == 0
    assert mock_client.place_trigger_order.call_count == 0

    assert signal_state.get_target("BTC") == 5000.0
    assert signal_state.get_direction("BTC") == 1

    signal_state.update_signal("ETH", -3000.0, 30.0, 3000.0, None)
    assert signal_state.get_target("ETH") == -3000.0
    assert signal_state.get_direction("ETH") == -1
    assert signal_state.get_target("BTC") == 5000.0

    signal_state.clear_signal("BTC")
    assert signal_state.get_target("BTC") == 0.0
    assert signal_state.get_direction("BTC") == 0


@pytest.mark.asyncio
async def test_startup_reconciliation_orphaned_position(
    settings, signal_state, mock_client
):
    """Bot startup with orphaned exchange position: sync → protect → stop placement."""

    engine = ExecutionEngine(signal_state, mock_client, settings, ["BTC"])
    stop_manager = StopManager(mock_client, settings)

    assert engine._position_sizes.get("BTC", 0.0) == 0.0
    assert engine._entry_prices.get("BTC", 0.0) == 0.0

    exchange_position = Position(
        symbol="BTC",
        side=PositionSide.LONG,
        size=0.1,
        entry_price=50000.0,
        current_price=50500.0,
        unrealized_pnl=50.0,
        leverage=2.0,
    )

    account_state = AccountState(
        wallet_address="0xTest",
        total_equity=100000.0,
        available_balance=95000.0,
        margin_used=5000.0,
        unrealized_pnl=50.0,
        positions={"BTC": exchange_position},
    )

    signal_state.update_signal("BTC", 5000.0, 50.0, 50000.0, None)

    await engine.sync_positions(account_state, {"BTC": 50500.0})

    assert engine._position_sizes["BTC"] == 0.1
    assert engine._entry_prices["BTC"] == 50000.0
    assert engine._last_executed_direction["BTC"] == 1

    signal_state.update_peak_trough("BTC", 50500.0)
    assert signal_state.peak_prices["BTC"] == 50500.0

    # ATR stop: peak=50500, stop=50500 - 8.0×50 = 50100, price=50050 < 50100
    mock_client.place_order = AsyncMock(
        return_value=_make_filled_order(side=OrderSide.SELL, size=0.1, price=50050.0)
    )

    async def on_closed(symbol: str):
        await stop_manager.cancel_stop(symbol)

    engine.on_position_closed = on_closed

    close_order = await engine.on_tick("BTC", 50050.0)
    assert close_order is not None
    assert close_order.status == OrderStatus.FILLED
    assert engine._position_sizes["BTC"] == 0.0

    engine.reset()
    signal_state.update_signal("BTC", 5000.0, 50.0, 50000.0, None)
    await engine.sync_positions(account_state, {"BTC": 50500.0})
    assert engine._position_sizes["BTC"] == 0.1

    # stop_price = entry - ATR × 8.0 × STOP_WIDENING_MULT = 50000 - 50×8.0×1.5 = 49400
    positions = {"BTC": exchange_position}
    atrs = {"BTC": 50.0}
    await stop_manager.refresh_stops(positions, atrs)

    stop = stop_manager.get_stop("BTC")
    assert stop is not None
    assert stop.price == 49400.0
    assert stop.side == OrderSide.SELL
    assert stop.size == 0.1
