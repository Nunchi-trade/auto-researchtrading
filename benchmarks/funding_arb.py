"""Funding rate carry strategy — ported from agent-cli."""

import numpy as np
from prepare import Signal, PortfolioState
from constants import BENCHMARK_SYMBOLS

ACTIVE_SYMBOLS = BENCHMARK_SYMBOLS
POSITION_SIZE_PCT = 0.10
FUNDING_ENTRY_THRESHOLD = (
    0.00005  # lower threshold for hourly data (funding is small per-hour)
)
FUNDING_EXIT_THRESHOLD = 0.00001  # exit when funding normalizes
LOOKBACK = 24  # hours to average funding
STOP_LOSS_PCT = 0.03
MAX_EXPOSURE_PCT = 0.30


class Strategy:
    def __init__(self):
        self.entry_prices = {}

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        total_exposure = sum(abs(v) for v in portfolio.positions.values())

        for symbol in ACTIVE_SYMBOLS:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < LOOKBACK:
                continue

            funding_rates = bd.history["funding_rate"].values[-LOOKBACK:]
            avg_funding = np.mean(funding_rates)
            current_pos = portfolio.positions.get(symbol, 0.0)
            mid = bd.close

            size = equity * POSITION_SIZE_PCT
            remaining_capacity = (
                equity * MAX_EXPOSURE_PCT - total_exposure + abs(current_pos)
            )
            size = min(size, max(0, remaining_capacity))

            target = current_pos

            # Carry trade: short when funding high (shorts get paid),
            # long when funding negative (longs get paid)
            if avg_funding > FUNDING_ENTRY_THRESHOLD:
                target = -size
            elif avg_funding < -FUNDING_ENTRY_THRESHOLD:
                target = size
            elif abs(avg_funding) < FUNDING_EXIT_THRESHOLD and current_pos != 0:
                target = 0.0

            # Stop loss
            if current_pos != 0 and symbol in self.entry_prices:
                entry = self.entry_prices[symbol]
                pnl_pct = (mid - entry) / entry
                if current_pos < 0:
                    pnl_pct = -pnl_pct
                if pnl_pct < -STOP_LOSS_PCT:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(Signal(symbol=symbol, target_position=target))
                if target != 0 and current_pos == 0:
                    self.entry_prices[symbol] = mid
                elif target == 0:
                    self.entry_prices.pop(symbol, None)

        return signals
