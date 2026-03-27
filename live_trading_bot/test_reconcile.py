"""Test that _reconcile_strategy_state restores orphaned positions.

Simulates the exact bug scenario:
1. Strategy generates an exit signal, pops its tracking state
2. Exchange rejects/fails the order — position remains open
3. On the next bar, reconciliation detects the desync and restores state
"""

import sys
import os
import logging

logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["BAR_INTERVAL"] = "1h"
os.environ["DRY_RUN"] = "true"

import numpy as np
import pandas as pd
from exchange.types import Candle, AccountState, Position, PositionSide
from adapter.adapter import LiveStrategyAdapter


def make_candles(symbol, base_price, n_bars=100):
    np.random.seed(42)
    candles = []
    price = base_price
    ts = 1700000000000
    for i in range(n_bars):
        price *= 1 + np.random.randn() * 0.005
        candles.append(
            Candle(
                symbol=symbol,
                timestamp=ts + i * 3600000,
                open=price,
                high=price * 1.005,
                low=price * 0.995,
                close=price,
                volume=1000.0,
                funding_rate=0.0001,
            )
        )
    return candles


def test_no_desync_normal_case():
    """Reconciliation is a no-op when strategy state matches exchange."""
    adapter = LiveStrategyAdapter()

    candles = make_candles("BTC", 100000.0)
    prices = {"BTC": candles[-1].close}

    adapter._strategy.entry_prices["BTC"] = 99000.0
    adapter._strategy.peak_prices["BTC"] = 101000.0
    adapter._strategy.atr_at_entry["BTC"] = 500.0

    state = AccountState(
        wallet_address="test",
        total_equity=100000.0,
        available_balance=20000.0,
        margin_used=80000.0,
        unrealized_pnl=0.0,
        positions={
            "BTC": Position(
                symbol="BTC",
                side=PositionSide.LONG,
                size=0.08,
                entry_price=99000.0,
                current_price=prices["BTC"],
                unrealized_pnl=0.0,
            )
        },
    )

    bar_data_input = {"BTC": candles}
    portfolio = adapter._account_to_portfolio(state, prices)
    bar_data = adapter._candles_to_bar_data(bar_data_input)

    adapter._reconcile_strategy_state(bar_data, portfolio, prices)

    assert adapter._strategy.entry_prices["BTC"] == 99000.0, (
        f"Entry should not change, got {adapter._strategy.entry_prices['BTC']}"
    )
    assert adapter._strategy.peak_prices["BTC"] == 101000.0, (
        f"Peak should not change, got {adapter._strategy.peak_prices['BTC']}"
    )
    assert adapter._strategy.atr_at_entry["BTC"] == 500.0, (
        f"ATR should not change, got {adapter._strategy.atr_at_entry['BTC']}"
    )

    print("PASS: no_desync_normal_case — state unchanged when in sync")


def test_desync_restores_state():
    """Reconciliation restores tracking state for orphaned positions."""
    adapter = LiveStrategyAdapter()

    candles = make_candles("BTC", 100000.0)
    prices = {"BTC": candles[-1].close}

    # Simulate the bug: strategy popped state after generating exit signal
    assert "BTC" not in adapter._strategy.entry_prices
    assert "BTC" not in adapter._strategy.peak_prices
    assert "BTC" not in adapter._strategy.atr_at_entry

    # But exchange says position is still open
    state = AccountState(
        wallet_address="test",
        total_equity=100000.0,
        available_balance=20000.0,
        margin_used=80000.0,
        unrealized_pnl=0.0,
        positions={
            "BTC": Position(
                symbol="BTC",
                side=PositionSide.LONG,
                size=0.08,
                entry_price=99000.0,
                current_price=prices["BTC"],
                unrealized_pnl=0.0,
            )
        },
    )

    bar_data_input = {"BTC": candles}
    portfolio = adapter._account_to_portfolio(state, prices)
    bar_data = adapter._candles_to_bar_data(bar_data_input)

    adapter._reconcile_strategy_state(bar_data, portfolio, prices)

    assert "BTC" in adapter._strategy.entry_prices, "Entry price should be restored"
    assert adapter._strategy.entry_prices["BTC"] == 99000.0, (
        f"Entry should be exchange entry price, got {adapter._strategy.entry_prices['BTC']}"
    )

    assert "BTC" in adapter._strategy.peak_prices, "Peak price should be restored"
    assert adapter._strategy.peak_prices["BTC"] == max(99000.0, prices["BTC"]), (
        f"Peak should be max(entry, current), got {adapter._strategy.peak_prices['BTC']}"
    )

    assert "BTC" in adapter._strategy.atr_at_entry, "ATR should be restored"
    assert adapter._strategy.atr_at_entry["BTC"] > 0, (
        f"ATR should be positive, got {adapter._strategy.atr_at_entry['BTC']}"
    )

    assert adapter._strategy.pyramided.get("BTC") is True, (
        "Restored position should be marked as already pyramided"
    )

    assert "BTC" not in adapter._strategy.exit_bar, (
        "Exit cooldown should be cleared for restored position"
    )

    print(
        f"PASS: desync_restores_state — entry={adapter._strategy.entry_prices['BTC']}, "
        f"peak={adapter._strategy.peak_prices['BTC']}, "
        f"atr={adapter._strategy.atr_at_entry['BTC']:.2f}"
    )


def test_desync_with_cooldown_cleared():
    """Reconciliation clears cooldown from failed exit so strategy can act."""
    adapter = LiveStrategyAdapter()

    candles = make_candles("BTC", 100000.0)
    prices = {"BTC": candles[-1].close}

    # Strategy popped state AND set cooldown (the full bug scenario)
    adapter._strategy.exit_bar["BTC"] = adapter._strategy.bar_count
    adapter._strategy.bar_count += 1

    state = AccountState(
        wallet_address="test",
        total_equity=100000.0,
        available_balance=20000.0,
        margin_used=80000.0,
        unrealized_pnl=0.0,
        positions={
            "BTC": Position(
                symbol="BTC",
                side=PositionSide.LONG,
                size=0.08,
                entry_price=99000.0,
                current_price=prices["BTC"],
                unrealized_pnl=0.0,
            )
        },
    )

    bar_data_input = {"BTC": candles}
    portfolio = adapter._account_to_portfolio(state, prices)
    bar_data = adapter._candles_to_bar_data(bar_data_input)

    # Without fix: cooldown is 1 bar old, bar_count is 1 — in_cooldown=True
    # strategy can't act on the position it can't track
    assert adapter._strategy.bar_count - adapter._strategy.exit_bar.get("BTC", -999) < 3

    adapter._reconcile_strategy_state(bar_data, portfolio, prices)

    assert "BTC" not in adapter._strategy.exit_bar, (
        "Cooldown should be cleared for orphaned position"
    )

    print("PASS: desync_with_cooldown_cleared — cooldown removed for restored position")


def test_no_position_no_op():
    """Reconciliation does nothing when there are no positions."""
    adapter = LiveStrategyAdapter()

    candles = make_candles("BTC", 100000.0)
    prices = {"BTC": candles[-1].close}

    state = AccountState(
        wallet_address="test",
        total_equity=100000.0,
        available_balance=100000.0,
        margin_used=0.0,
        unrealized_pnl=0.0,
        positions={},
    )

    bar_data_input = {"BTC": candles}
    portfolio = adapter._account_to_portfolio(state, prices)
    bar_data = adapter._candles_to_bar_data(bar_data_input)

    adapter._reconcile_strategy_state(bar_data, portfolio, prices)

    assert len(adapter._strategy.entry_prices) == 0
    assert len(adapter._strategy.peak_prices) == 0
    assert len(adapter._strategy.atr_at_entry) == 0

    print("PASS: no_position_no_op — nothing added when no positions exist")


def test_short_position_restored():
    """Reconciliation works for short positions too."""
    adapter = LiveStrategyAdapter()

    candles = make_candles("BTC", 100000.0)
    prices = {"BTC": candles[-1].close}

    state = AccountState(
        wallet_address="test",
        total_equity=100000.0,
        available_balance=20000.0,
        margin_used=80000.0,
        unrealized_pnl=0.0,
        positions={
            "BTC": Position(
                symbol="BTC",
                side=PositionSide.SHORT,
                size=0.08,
                entry_price=101000.0,
                current_price=prices["BTC"],
                unrealized_pnl=0.0,
            )
        },
    )

    bar_data_input = {"BTC": candles}
    portfolio = adapter._account_to_portfolio(state, prices)
    bar_data = adapter._candles_to_bar_data(bar_data_input)

    adapter._reconcile_strategy_state(bar_data, portfolio, prices)

    assert "BTC" in adapter._strategy.entry_prices
    assert adapter._strategy.entry_prices["BTC"] == 101000.0
    assert "BTC" in adapter._strategy.peak_prices

    print(
        f"PASS: short_position_restored — entry={adapter._strategy.entry_prices['BTC']}"
    )


if __name__ == "__main__":
    test_no_desync_normal_case()
    test_desync_restores_state()
    test_desync_with_cooldown_cleared()
    test_no_position_no_op()
    test_short_position_restored()
    print(f"\nAll 5 tests passed.")
