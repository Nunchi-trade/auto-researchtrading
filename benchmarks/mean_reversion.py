"""Mean reversion z-score strategy — ported from agent-cli."""

import numpy as np
from prepare import Signal, PortfolioState, BarData
from constants import BENCHMARK_SYMBOLS

ACTIVE_SYMBOLS = BENCHMARK_SYMBOLS
WINDOW = 24
ENTRY_ZSCORE = 2.0
EXIT_ZSCORE = 0.5
POSITION_SIZE_PCT = 0.10
STOP_LOSS_PCT = 0.04


class Strategy:
    def __init__(self):
        self.entry_prices = {}

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash

        for symbol in ACTIVE_SYMBOLS:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < WINDOW:
                continue

            closes = bd.history["close"].values[-WINDOW:]
            sma = np.mean(closes)
            std = np.std(closes)
            mid = bd.close
            current_pos = portfolio.positions.get(symbol, 0.0)

            if std <= 0:
                continue

            zscore = (mid - sma) / std
            size = equity * POSITION_SIZE_PCT
            target = current_pos

            # Enter on extreme z-scores
            if zscore > ENTRY_ZSCORE:
                target = -size  # overbought → short
            elif zscore < -ENTRY_ZSCORE:
                target = size  # oversold → long
            # Exit when z-score normalizes
            elif abs(zscore) < EXIT_ZSCORE and current_pos != 0:
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
