"""Avellaneda-Stoikov inventory-aware market maker — ported from agent-cli."""

import math
import numpy as np
from prepare import Signal, PortfolioState, BarData
from constants import BENCHMARK_SYMBOLS

GAMMA = 0.1
K = 1.5
POSITION_SIZE_PCT = 0.08
MAX_INVENTORY_PCT = 0.25
MIN_SPREAD_BPS = 20.0  # wider for hourly bars (not tick-level)
MAX_SPREAD_BPS = 500.0
VOL_WINDOW = 30
ACTIVE_SYMBOLS = BENCHMARK_SYMBOLS


class Strategy:
    def __init__(self):
        self.entry_prices = {}

    def _compute_vol(self, closes):
        if len(closes) < 3:
            return 0.001
        log_rets = np.diff(np.log(closes[-VOL_WINDOW:]))
        return max(np.std(log_rets), 1e-6)

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
            mid = bd.close
            sigma = self._compute_vol(closes) * mid

            current_pos = portfolio.positions.get(symbol, 0.0)
            max_inv = equity * MAX_INVENTORY_PCT
            q = current_pos / max_inv if max_inv > 0 else 0.0

            # Reservation price: skew away from inventory
            T = 1.0
            r_price = mid - q * GAMMA * sigma**2 * T

            # Optimal spread
            spread = GAMMA * sigma**2 * T
            if GAMMA > 0:
                spread += (2.0 / GAMMA) * math.log(1.0 + GAMMA / K)

            half_spread = max(
                mid * MIN_SPREAD_BPS / 10000,
                min(spread / 2, mid * MAX_SPREAD_BPS / 10000),
            )

            bid_price = r_price - half_spread
            ask_price = r_price + half_spread

            # Size scaled by inventory utilization
            utilization = abs(current_pos) / max_inv if max_inv > 0 else 0
            size = equity * POSITION_SIZE_PCT * max(0.1, 1.0 - utilization)

            # Use reservation price vs mid as directional signal
            target = current_pos
            price_diff_pct = (r_price - mid) / mid
            if price_diff_pct > 0.001:  # reservation above mid → buy
                target = size
            elif price_diff_pct < -0.001:  # reservation below mid → sell
                target = -size
            elif abs(price_diff_pct) < 0.0003 and current_pos != 0:
                target = 0.0

            # Stop loss
            if current_pos != 0 and symbol in self.entry_prices:
                entry = self.entry_prices[symbol]
                pnl = (mid - entry) / entry
                if current_pos < 0:
                    pnl = -pnl
                if pnl < -0.03:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(Signal(symbol=symbol, target_position=target))
                if target != 0 and current_pos == 0:
                    self.entry_prices[symbol] = mid
                elif target == 0:
                    self.entry_prices.pop(symbol, None)

        return signals
