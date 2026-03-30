"""Volatility-regime adaptive strategy — ported from agent-cli."""

import math
import numpy as np
from prepare import Signal, PortfolioState, BarData
from constants import BENCHMARK_SYMBOLS

VOL_WINDOW = 48
ACTIVE_SYMBOLS = BENCHMARK_SYMBOLS

# Regime params: (vol_threshold, spread_bps, size_mult, stop_mult)
REGIMES = [
    (0.30, 10, 1.5, 0.02),  # I_low: tight spread, big size, tight stop
    (0.60, 25, 1.0, 0.03),  # II_normal
    (1.00, 50, 0.5, 0.05),  # III_high: wide spread, small size
    (float("inf"), 100, 0.2, 0.08),  # IV_extreme: survival
]
HYSTERESIS = 3
BASE_SIZE_PCT = 0.08


class Strategy:
    def __init__(self):
        self.entry_prices = {}
        self.regime_idx = {s: 1 for s in ACTIVE_SYMBOLS}
        self.down_count = {s: 0 for s in ACTIVE_SYMBOLS}
        self.down_candidate = {s: -1 for s in ACTIVE_SYMBOLS}

    def _classify(self, symbol, ann_vol):
        target = 0
        for i, (thresh, _, _, _) in enumerate(REGIMES):
            if ann_vol < thresh:
                target = i
                break

        curr = self.regime_idx[symbol]
        if target > curr:
            self.regime_idx[symbol] = target
            self.down_count[symbol] = 0
        elif target < curr:
            if target == self.down_candidate[symbol]:
                self.down_count[symbol] += 1
            else:
                self.down_candidate[symbol] = target
                self.down_count[symbol] = 1
            if self.down_count[symbol] >= HYSTERESIS:
                self.regime_idx[symbol] = target
                self.down_count[symbol] = 0
        else:
            self.down_count[symbol] = 0

        return REGIMES[self.regime_idx[symbol]]

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash

        for symbol in ACTIVE_SYMBOLS:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < VOL_WINDOW:
                continue

            closes = bd.history["close"].values
            log_rets = np.diff(np.log(closes[-VOL_WINDOW:]))
            ann_vol = np.std(log_rets) * math.sqrt(8760) if len(log_rets) > 1 else 0.5

            _, spread_bps, size_mult, stop_mult = self._classify(symbol, ann_vol)
            mid = bd.close
            current_pos = portfolio.positions.get(symbol, 0.0)

            half_spread = mid * spread_bps / 10000
            size = equity * BASE_SIZE_PCT * size_mult

            # Simple momentum signal within regime-adaptive framework
            sma_fast = np.mean(closes[-12:])
            sma_slow = np.mean(closes[-48:]) if len(closes) >= 48 else np.mean(closes)

            target = current_pos
            if sma_fast > sma_slow * (1 + spread_bps / 20000):
                target = size
            elif sma_fast < sma_slow * (1 - spread_bps / 20000):
                target = -size

            # Stop loss based on regime
            if current_pos != 0 and symbol in self.entry_prices:
                entry = self.entry_prices[symbol]
                pnl_pct = (mid - entry) / entry
                if current_pos < 0:
                    pnl_pct = -pnl_pct
                if pnl_pct < -stop_mult:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(Signal(symbol=symbol, target_position=target))
                if target != 0 and current_pos == 0:
                    self.entry_prices[symbol] = mid
                elif target == 0:
                    self.entry_prices.pop(symbol, None)

        return signals
