"""RSI mean reversion — buy oversold, sell overbought."""
import numpy as np
from prepare import Signal, PortfolioState, BarData, SYMBOLS

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_EXIT_LOW = 45
RSI_EXIT_HIGH = 55
POSITION_SIZE_PCT = 0.08
STOP_LOSS_PCT = 0.05


def calc_rsi(closes, period):
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    rs = avg_gain / max(avg_loss, 1e-10)
    return 100 - 100 / (1 + rs)


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
            if len(bd.history) < RSI_PERIOD + 1:
                continue

            closes = bd.history["close"].values
            mid = bd.close
            current_pos = portfolio.positions.get(symbol, 0.0)
            size = equity * POSITION_SIZE_PCT

            rsi = calc_rsi(closes, RSI_PERIOD)
            target = current_pos

            if current_pos == 0:
                if rsi < RSI_OVERSOLD:
                    target = size  # oversold → long
                elif rsi > RSI_OVERBOUGHT:
                    target = -size  # overbought → short
            else:
                # Exit when RSI normalizes
                if current_pos > 0 and rsi > RSI_EXIT_HIGH:
                    target = 0.0
                elif current_pos < 0 and rsi < RSI_EXIT_LOW:
                    target = 0.0

                # Stop loss
                if symbol in self.entry_prices:
                    pnl_pct = (mid - self.entry_prices[symbol]) / self.entry_prices[symbol]
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
