"""Momentum breakout with volume confirmation — ported from agent-cli."""

import numpy as np
from prepare import Signal, PortfolioState
from constants import BENCHMARK_SYMBOLS

ACTIVE_SYMBOLS = BENCHMARK_SYMBOLS
LOOKBACK = 48
BREAKOUT_THRESHOLD = 0.008  # 0.8% for hourly
VOLUME_SURGE_MULT = 1.0  # no volume filter (volume data may be spotty)
TRAILING_STOP_BPS = 200  # 2% trailing stop
POSITION_SIZE_PCT = 0.10
MAX_HOLD_BARS = 72


class Strategy:
    def __init__(self):
        self.entry_prices = {}
        self.peak_prices = {}
        self.bars_held = {}

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash

        for symbol in ACTIVE_SYMBOLS:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < LOOKBACK:
                continue

            highs = bd.history["high"].values[-LOOKBACK:]
            lows = bd.history["low"].values[-LOOKBACK:]
            volumes = bd.history["volume"].values[-LOOKBACK:]

            period_high = np.max(highs)
            period_low = np.min(lows)
            avg_vol = np.mean(volumes) if len(volumes) > 0 else 1
            mid = bd.close
            current_pos = portfolio.positions.get(symbol, 0.0)
            size = equity * POSITION_SIZE_PCT
            target = current_pos

            vol_surge = (
                bd.volume > avg_vol * VOLUME_SURGE_MULT if avg_vol > 0 else False
            )

            # Breakout entry
            if current_pos == 0:
                up_break = (mid - period_high) / period_high if period_high > 0 else 0
                dn_break = (period_low - mid) / period_low if period_low > 0 else 0

                if up_break > BREAKOUT_THRESHOLD and vol_surge:
                    target = size
                elif dn_break > BREAKOUT_THRESHOLD and vol_surge:
                    target = -size
            else:
                # Track holding time
                self.bars_held[symbol] = self.bars_held.get(symbol, 0) + 1

                # Trailing stop
                if symbol not in self.peak_prices:
                    self.peak_prices[symbol] = mid
                if current_pos > 0:
                    self.peak_prices[symbol] = max(self.peak_prices[symbol], mid)
                    stop = self.peak_prices[symbol] * (1 - TRAILING_STOP_BPS / 10000)
                    if mid < stop:
                        target = 0.0
                else:
                    self.peak_prices[symbol] = min(self.peak_prices[symbol], mid)
                    stop = self.peak_prices[symbol] * (1 + TRAILING_STOP_BPS / 10000)
                    if mid > stop:
                        target = 0.0

                # Max hold time
                if self.bars_held.get(symbol, 0) > MAX_HOLD_BARS:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(Signal(symbol=symbol, target_position=target))
                if target != 0 and current_pos == 0:
                    self.entry_prices[symbol] = mid
                    self.peak_prices[symbol] = mid
                    self.bars_held[symbol] = 0
                elif target == 0:
                    self.entry_prices.pop(symbol, None)
                    self.peak_prices.pop(symbol, None)
                    self.bars_held.pop(symbol, None)

        return signals
