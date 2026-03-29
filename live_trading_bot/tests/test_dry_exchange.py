"""Tests for DryExchange position tracking and simulated fills.

What these tests tell us:
- _apply_fill correctly updates internal position state for all order flows
- get_account_state returns equity and positions consistent with simulated fills
- The bot can trust DryExchange the same way it trusts the live exchange
"""

import pytest
from unittest.mock import AsyncMock, patch

from exchange.dry_exchange import DryExchange, _SimPosition
from exchange.types import OrderSide, OrderType, OrderStatus, PositionSide


@pytest.fixture
def exchange():
    """Create a DryExchange with mocked Info API (no real network calls)."""
    with patch("exchange.dry_exchange.Info"):
        with patch("exchange.dry_exchange.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"
            settings.HYPERLIQUID_MAIN_WALLET = None
            settings.DRY_RUN_INITIAL_CAPITAL = 10_000.0
            settings.MAX_LEVERAGE = 5.0

            # Use a valid 32-byte hex key for Account.from_key
            ex = DryExchange(
                private_key="0x" + "ab" * 32
            )
            return ex


class TestApplyFill:
    """What _apply_fill tells us: position state transitions are correct."""

    def test_open_long(self, exchange):
        exchange._apply_fill("BTC", OrderSide.BUY, 0.1, 50000.0, False)

        pos = exchange._positions["BTC"]
        assert pos.is_long is True
        assert pos.size == 0.1
        assert pos.entry_price == 50000.0

    def test_open_short(self, exchange):
        exchange._apply_fill("ETH", OrderSide.SELL, 1.0, 3000.0, False)

        pos = exchange._positions["ETH"]
        assert pos.is_long is False
        assert pos.size == 1.0
        assert pos.entry_price == 3000.0

    def test_close_long_realizes_pnl(self, exchange):
        exchange._apply_fill("BTC", OrderSide.BUY, 0.1, 50000.0, False)
        exchange._apply_fill("BTC", OrderSide.SELL, 0.1, 52000.0, True)

        assert "BTC" not in exchange._positions
        # PnL = (52000 - 50000) * 0.1 = 200
        assert exchange._realized_pnl == pytest.approx(200.0)

    def test_close_short_realizes_pnl(self, exchange):
        exchange._apply_fill("ETH", OrderSide.SELL, 1.0, 3000.0, False)
        exchange._apply_fill("ETH", OrderSide.BUY, 1.0, 2800.0, True)

        assert "ETH" not in exchange._positions
        # PnL = (3000 - 2800) * 1.0 = 200
        assert exchange._realized_pnl == pytest.approx(200.0)

    def test_partial_close(self, exchange):
        exchange._apply_fill("BTC", OrderSide.BUY, 0.2, 50000.0, False)
        exchange._apply_fill("BTC", OrderSide.SELL, 0.1, 51000.0, True)

        pos = exchange._positions["BTC"]
        assert pos.size == pytest.approx(0.1)
        assert pos.entry_price == 50000.0
        # PnL = (51000 - 50000) * 0.1 = 100
        assert exchange._realized_pnl == pytest.approx(100.0)

    def test_reversal_without_reduce_only(self, exchange):
        """Close long then open short in a single fill (no reduce_only)."""
        exchange._apply_fill("BTC", OrderSide.BUY, 0.1, 50000.0, False)
        # Sell 0.2 without reduce_only: closes 0.1 long, opens 0.1 short
        exchange._apply_fill("BTC", OrderSide.SELL, 0.2, 51000.0, False)

        pos = exchange._positions["BTC"]
        assert pos.is_long is False
        assert pos.size == pytest.approx(0.1)
        assert pos.entry_price == 51000.0
        # Realized from closing the long: (51000 - 50000) * 0.1 = 100
        assert exchange._realized_pnl == pytest.approx(100.0)

    def test_add_to_position_averages_entry(self, exchange):
        exchange._apply_fill("BTC", OrderSide.BUY, 0.1, 50000.0, False)
        exchange._apply_fill("BTC", OrderSide.BUY, 0.1, 52000.0, False)

        pos = exchange._positions["BTC"]
        assert pos.size == pytest.approx(0.2)
        assert pos.entry_price == pytest.approx(51000.0)
        assert exchange._realized_pnl == 0.0

    def test_reduce_only_on_empty_position_is_noop(self, exchange):
        exchange._apply_fill("BTC", OrderSide.SELL, 0.1, 50000.0, True)
        assert "BTC" not in exchange._positions


class TestPlaceOrder:
    """What place_order tells us: orders fill at the given price and update positions."""

    @pytest.mark.asyncio
    async def test_market_order_fills_and_tracks(self, exchange):
        exchange.get_mid_price = AsyncMock(return_value=50000.0)

        order = await exchange.place_order(
            "BTC", OrderSide.BUY, 0.1, OrderType.MARKET
        )

        assert order.status == OrderStatus.FILLED
        assert order.filled_size == 0.1
        assert order.avg_fill_price == 50000.0
        assert "BTC" in exchange._positions

    @pytest.mark.asyncio
    async def test_explicit_price_used(self, exchange):
        order = await exchange.place_order(
            "ETH", OrderSide.SELL, 1.0, OrderType.MARKET, price=3500.0
        )

        assert order.avg_fill_price == 3500.0
        assert exchange._positions["ETH"].entry_price == 3500.0


class TestAccountState:
    """What get_account_state tells us: equity and positions reflect all simulated fills."""

    @pytest.mark.asyncio
    async def test_initial_state(self, exchange):
        exchange.get_all_mid_prices = AsyncMock(return_value={})

        state = await exchange.get_account_state()

        assert state.total_equity == pytest.approx(10_000.0)
        assert state.positions == {}

    @pytest.mark.asyncio
    async def test_equity_includes_unrealized_pnl(self, exchange):
        exchange._apply_fill("BTC", OrderSide.BUY, 0.1, 50000.0, False)
        exchange.get_all_mid_prices = AsyncMock(
            return_value={"BTC": 52000.0}
        )

        state = await exchange.get_account_state()

        # Unrealized PnL = (52000 - 50000) * 0.1 = 200
        assert state.total_equity == pytest.approx(10_200.0)
        assert state.unrealized_pnl == pytest.approx(200.0)

        pos = state.positions["BTC"]
        assert pos.side == PositionSide.LONG
        assert pos.size == 0.1
        assert pos.entry_price == 50000.0
        assert pos.current_price == 52000.0

    @pytest.mark.asyncio
    async def test_equity_after_realized_loss(self, exchange):
        exchange._apply_fill("BTC", OrderSide.BUY, 0.1, 50000.0, False)
        exchange._apply_fill("BTC", OrderSide.SELL, 0.1, 48000.0, True)
        exchange.get_all_mid_prices = AsyncMock(return_value={})

        state = await exchange.get_account_state()

        # Realized PnL = (48000 - 50000) * 0.1 = -200
        assert state.total_equity == pytest.approx(9_800.0)
        assert state.positions == {}
