"""Simple 20-day momentum — long only, fixed position sizing."""
import numpy as np
from prepare import Signal, PortfolioState, BarData, SYMBOLS

LOOKBACK = 20
THRESHOLD = 0.02
POSITION_SIZE_PCT = 0.08
STOP_LOSS_PCT = 0.05


class Strategy:
    def __init__(self, symbols=None):
        self.symbols = symbols or SYMBOLS
        self.entry_prices = {}

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash

        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < LOOKBACK + 1:
                continue

            closes = bd.history["close"].values
            mid = bd.close
            current_pos = portfolio.positions.get(symbol, 0.0)
            size = equity * POSITION_SIZE_PCT

            ret = (closes[-1] - closes[-LOOKBACK]) / closes[-LOOKBACK]
            target = current_pos

            if current_pos == 0:
                if ret > THRESHOLD:
                    target = size
            else:
                # Stop loss
                if symbol in self.entry_prices:
                    pnl_pct = (mid - self.entry_prices[symbol]) / self.entry_prices[symbol]
                    if pnl_pct < -STOP_LOSS_PCT:
                        target = 0.0
                # Exit when momentum fades
                if ret < 0:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(Signal(symbol=symbol, target_position=target))
                if target != 0 and current_pos == 0:
                    self.entry_prices[symbol] = mid
                elif target == 0:
                    self.entry_prices.pop(symbol, None)

        return signals
