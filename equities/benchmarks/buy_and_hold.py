"""Buy and hold — equal-weight all symbols on first bar, never trade again."""
import numpy as np
from prepare import Signal, PortfolioState, BarData, SYMBOLS

POSITION_SIZE_PCT = 0.08


class Strategy:
    def __init__(self, symbols=None):
        self.symbols = symbols or SYMBOLS
        self.initialized = False

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list:
        if self.initialized:
            return []

        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        size = equity * POSITION_SIZE_PCT

        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            signals.append(Signal(symbol=symbol, target_position=size))

        if signals:
            self.initialized = True
        return signals
