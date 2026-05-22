"""50/200 SMA crossover (golden cross / death cross) — classic equity trend following."""
import numpy as np
from prepare import Signal, PortfolioState, BarData, SYMBOLS

FAST_SMA = 50
SLOW_SMA = 200
POSITION_SIZE_PCT = 0.08


class Strategy:
    def __init__(self, symbols=None):
        self.symbols = symbols or SYMBOLS

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash

        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < SLOW_SMA:
                continue

            closes = bd.history["close"].values
            current_pos = portfolio.positions.get(symbol, 0.0)
            size = equity * POSITION_SIZE_PCT

            fast = np.mean(closes[-FAST_SMA:])
            slow = np.mean(closes[-SLOW_SMA:])
            target = current_pos

            if fast > slow and current_pos <= 0:
                target = size  # golden cross → long
            elif fast < slow and current_pos >= 0:
                target = 0.0 if current_pos > 0 else -size  # death cross

            if abs(target - current_pos) > 1.0:
                signals.append(Signal(symbol=symbol, target_position=target))

        return signals
