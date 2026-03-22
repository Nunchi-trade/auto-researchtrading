"""
Equities momentum ensemble strategy.
Adapted from Nunchi's auto-researchtrading — crypto-specific logic removed.

5-signal ensemble: momentum, EMA crossover, RSI, MACD, BB compression.
3/5 majority vote for entries. ATR trailing stop for exits.
"""

import numpy as np
from prepare import Signal, PortfolioState, BarData

ACTIVE_SYMBOLS = ["SPY", "QQQ", "IWM", "XLE", "XLF", "TLT", "AAPL", "NVDA", "JPM", "UNH"]

SHORT_WINDOW = 5
MED_WINDOW = 10
LONG_WINDOW = 20
EMA_FAST = 10
EMA_SLOW = 30
RSI_PERIOD = 8
RSI_BULL = 50
RSI_BEAR = 50
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BB_PERIOD = 20

BASE_POSITION_PCT = 0.08
VOL_LOOKBACK = 20
TARGET_VOL = 0.01
ATR_LOOKBACK = 14
ATR_STOP_MULT = 2.5
TAKE_PROFIT_PCT = 99.0
BASE_THRESHOLD = 0.01

COOLDOWN_BARS = 2
MIN_VOTES = 3


def ema(values, span):
    alpha = 2.0 / (span + 1)
    result = np.empty_like(values, dtype=float)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


def calc_rsi(closes, period):
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1) :])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    rs = avg_gain / max(avg_loss, 1e-10)
    return 100 - 100 / (1 + rs)


class Strategy:
    def __init__(self, symbols=None):
        self.symbols = symbols or ACTIVE_SYMBOLS
        self.entry_prices = {}
        self.peak_prices = {}
        self.atr_at_entry = {}
        self.pyramided = {}
        self.peak_equity = 100000.0
        self.exit_bar = {}
        self.bar_count = 0

    def _calc_atr(self, history, lookback):
        if len(history) < lookback + 1:
            return None
        highs = history["high"].values[-lookback:]
        lows = history["low"].values[-lookback:]
        closes = history["close"].values[-(lookback + 1) : -1]
        tr = np.maximum(
            highs - lows, np.maximum(np.abs(highs - closes), np.abs(lows - closes))
        )
        return np.mean(tr)

    def _calc_vol(self, closes, lookback):
        if len(closes) < lookback:
            return TARGET_VOL
        log_rets = np.diff(np.log(closes[-lookback:]))
        return max(np.std(log_rets), 1e-6)

    def _calc_macd(self, closes):
        if len(closes) < MACD_SLOW + MACD_SIGNAL + 5:
            return 0.0
        fast_ema = ema(closes[-(MACD_SLOW + MACD_SIGNAL + 5) :], MACD_FAST)
        slow_ema = ema(closes[-(MACD_SLOW + MACD_SIGNAL + 5) :], MACD_SLOW)
        macd_line = fast_ema - slow_ema
        signal_line = ema(macd_line, MACD_SIGNAL)
        return macd_line[-1] - signal_line[-1]

    def _calc_bb_width_pctile(self, closes, period):
        if len(closes) < period * 3:
            return 50.0
        widths = []
        for i in range(period * 2, len(closes)):
            window = closes[i - period : i]
            sma = np.mean(window)
            std = np.std(window)
            width = (2 * std) / sma if sma > 0 else 0
            widths.append(width)
        if len(widths) < 2:
            return 50.0
        current_width = widths[-1]
        pctile = 100 * np.sum(np.array(widths) <= current_width) / len(widths)
        return pctile

    def on_bar(self, bar_data, portfolio):
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        self.bar_count += 1

        self.peak_equity = max(self.peak_equity, equity)
        current_dd = (self.peak_equity - equity) / self.peak_equity
        dd_scale = 1.0

        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if (
                len(bd.history)
                < max(LONG_WINDOW, EMA_SLOW, MACD_SLOW + MACD_SIGNAL + 5, BB_PERIOD * 3)
                + 1
            ):
                continue

            closes = bd.history["close"].values
            mid = bd.close

            realized_vol = self._calc_vol(closes, VOL_LOOKBACK)
            vol_ratio = realized_vol / TARGET_VOL
            dyn_threshold = BASE_THRESHOLD * (0.3 + vol_ratio * 0.7)
            dyn_threshold = max(0.005, min(0.030, dyn_threshold))

            ret_short = (closes[-1] - closes[-MED_WINDOW]) / closes[-MED_WINDOW]
            ret_long = (closes[-1] - closes[-LONG_WINDOW]) / closes[-LONG_WINDOW]

            mom_bull = ret_short > dyn_threshold
            mom_bear = ret_short < -dyn_threshold

            ema_fast_arr = ema(closes[-(EMA_SLOW + 10) :], EMA_FAST)
            ema_slow_arr = ema(closes[-(EMA_SLOW + 10) :], EMA_SLOW)
            ema_bull = ema_fast_arr[-1] > ema_slow_arr[-1]
            ema_bear = ema_fast_arr[-1] < ema_slow_arr[-1]

            rsi = calc_rsi(closes, RSI_PERIOD)
            rsi_bull = rsi > RSI_BULL
            rsi_bear = rsi < RSI_BEAR

            macd_hist = self._calc_macd(closes)
            macd_bull = macd_hist > 0
            macd_bear = macd_hist < 0

            bb_pctile = self._calc_bb_width_pctile(closes, BB_PERIOD)
            bb_compressed = bb_pctile < 85

            bull_votes = sum([mom_bull, ema_bull, rsi_bull, macd_bull, bb_compressed])
            bear_votes = sum([mom_bear, ema_bear, rsi_bear, macd_bear, bb_compressed])

            bullish = bull_votes >= MIN_VOTES
            bearish = bear_votes >= MIN_VOTES

            in_cooldown = (
                self.bar_count - self.exit_bar.get(symbol, -999)
            ) < COOLDOWN_BARS

            size = equity * BASE_POSITION_PCT * dd_scale

            current_pos = portfolio.positions.get(symbol, 0.0)
            target = current_pos

            if current_pos == 0:
                if not in_cooldown:
                    if bullish:
                        target = size
                        self.pyramided[symbol] = False
                    elif bearish:
                        target = -size
                        self.pyramided[symbol] = False
            else:
                atr = self._calc_atr(bd.history, ATR_LOOKBACK)
                if atr is None:
                    atr = self.atr_at_entry.get(symbol, mid * 0.02)

                if symbol not in self.peak_prices:
                    self.peak_prices[symbol] = mid

                if current_pos > 0:
                    self.peak_prices[symbol] = max(self.peak_prices[symbol], mid)
                    stop = self.peak_prices[symbol] - ATR_STOP_MULT * atr
                    if mid < stop:
                        target = 0.0
                else:
                    self.peak_prices[symbol] = min(self.peak_prices[symbol], mid)
                    stop = self.peak_prices[symbol] + ATR_STOP_MULT * atr
                    if mid > stop:
                        target = 0.0

                if current_pos > 0 and rsi > RSI_OVERBOUGHT:
                    target = 0.0
                elif current_pos < 0 and rsi < RSI_OVERSOLD:
                    target = 0.0

                if current_pos > 0 and bearish and not in_cooldown:
                    target = -size
                elif current_pos < 0 and bullish and not in_cooldown:
                    target = size

            if abs(target - current_pos) > 1.0:
                signals.append(Signal(symbol=symbol, target_position=target))
                if target != 0 and current_pos == 0:
                    self.entry_prices[symbol] = mid
                    self.peak_prices[symbol] = mid
                    self.atr_at_entry[symbol] = (
                        self._calc_atr(bd.history, ATR_LOOKBACK) or mid * 0.02
                    )
                elif target == 0:
                    self.entry_prices.pop(symbol, None)
                    self.peak_prices.pop(symbol, None)
                    self.atr_at_entry.pop(symbol, None)
                    self.pyramided.pop(symbol, None)
                    self.exit_bar[symbol] = self.bar_count
                elif (target > 0 and current_pos < 0) or (
                    target < 0 and current_pos > 0
                ):
                    self.entry_prices[symbol] = mid
                    self.peak_prices[symbol] = mid
                    self.atr_at_entry[symbol] = (
                        self._calc_atr(bd.history, ATR_LOOKBACK) or mid * 0.02
                    )
                    self.pyramided[symbol] = False

        return signals
