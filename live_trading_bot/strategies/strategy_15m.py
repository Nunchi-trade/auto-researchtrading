"""15-minute resolution strategy — scaled from hourly base (1 hour = 4 bars)."""

import json
from pathlib import Path

import numpy as np
from prepare import Signal, PortfolioState, BarData

ACTIVE_SYMBOLS = ["BTC", "ETH", "SOL", "XRP"]
SYMBOL_WEIGHTS = {"BTC": 0.25, "ETH": 0.25, "SOL": 0.25, "XRP": 0.25}

SHORT_WINDOW = 24  # 6h
MED_WINDOW = 48  # 12h
MED2_WINDOW = 96  # 24h
LONG_WINDOW = 144  # 36h
EMA_FAST = 28  # 7h
EMA_SLOW = 104  # 26h
RSI_PERIOD = 28  # 7h
RSI_BULL = 50
RSI_BEAR = 50
RSI_OVERBOUGHT = 65
RSI_OVERSOLD = 35

MACD_FAST = 56  # 14h
MACD_SLOW = 92  # 23h
MACD_SIGNAL = 36  # 9h

BB_PERIOD = 28  # 7h

FUNDING_LOOKBACK = 96  # 24h
FUNDING_BOOST = 0.0
BASE_POSITION_PCT = 2.00
VOL_LOOKBACK = 144  # 36h
TARGET_VOL = 0.015
ATR_LOOKBACK = 96  # 24h
ATR_STOP_MULT = 8.0
TAKE_PROFIT_PCT = 99.0
BASE_THRESHOLD = 0.012
BTC_OPPOSE_THRESHOLD = -99.0

PYRAMID_THRESHOLD = 0.015
PYRAMID_SIZE = 0.0
CORR_LOOKBACK = 288  # 72h
HIGH_CORR_THRESHOLD = 99.0

DD_REDUCE_THRESHOLD = 99.0
DD_REDUCE_SCALE = 0.5

COOLDOWN_BARS = 12  # 3h cooldown
MIN_VOTES = 5

# Tunable thresholds (were hardcoded in on_bar)
THRESHOLD_MIN = 0.005
THRESHOLD_MAX = 0.020
BB_COMPRESS_PCTILE = 90


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
    def __init__(self):
        self.entry_prices = {}
        self.peak_prices = {}
        self.atr_at_entry = {}
        self.btc_momentum = 0.0
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

    def _calc_correlation(self, bar_data):
        if "BTC" not in bar_data or "ETH" not in bar_data:
            return 0.5
        btc_h = bar_data["BTC"].history
        eth_h = bar_data["ETH"].history
        if len(btc_h) < CORR_LOOKBACK or len(eth_h) < CORR_LOOKBACK:
            return 0.5
        btc_rets = np.diff(np.log(btc_h["close"].values[-CORR_LOOKBACK:]))
        eth_rets = np.diff(np.log(eth_h["close"].values[-CORR_LOOKBACK:]))
        if len(btc_rets) < 10:
            return 0.5
        corr = np.corrcoef(btc_rets, eth_rets)[0, 1]
        return corr if not np.isnan(corr) else 0.5

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
        n = len(closes)
        windows = np.lib.stride_tricks.sliding_window_view(closes, period)
        sma = windows.mean(axis=1)
        std = windows.std(axis=1)
        widths = np.where(sma > 0, (2 * std) / sma, 0.0)
        valid = widths[period:]
        if len(valid) < 2:
            return 50.0
        current_width = valid[
            -2
        ]  # match original: closes[n-1-period:n-1] excludes current bar
        pctile = 100 * np.sum(valid[:-1] <= current_width) / len(valid[:-1])
        return pctile

    def on_bar(self, bar_data, portfolio):
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        self.bar_count += 1

        self.peak_equity = max(self.peak_equity, equity)
        current_dd = (self.peak_equity - equity) / self.peak_equity
        dd_scale = 1.0
        if current_dd > DD_REDUCE_THRESHOLD:
            dd_scale = max(
                DD_REDUCE_SCALE, 1.0 - (current_dd - DD_REDUCE_THRESHOLD) * 5
            )

        if "BTC" in bar_data and len(bar_data["BTC"].history) >= LONG_WINDOW + 1:
            btc_closes = bar_data["BTC"].history["close"].values
            self.btc_momentum = (
                btc_closes[-1] - btc_closes[-MED2_WINDOW]
            ) / btc_closes[-MED2_WINDOW]

        btc_eth_corr = self._calc_correlation(bar_data)
        high_corr = btc_eth_corr > HIGH_CORR_THRESHOLD

        for symbol in ACTIVE_SYMBOLS:
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
            dyn_threshold = max(THRESHOLD_MIN, min(THRESHOLD_MAX, dyn_threshold))

            ret_vshort = (closes[-1] - closes[-SHORT_WINDOW]) / closes[-SHORT_WINDOW]
            ret_short = (closes[-1] - closes[-MED_WINDOW]) / closes[-MED_WINDOW]
            ret_med = (closes[-1] - closes[-MED2_WINDOW]) / closes[-MED2_WINDOW]
            ret_long = (closes[-1] - closes[-LONG_WINDOW]) / closes[-LONG_WINDOW]

            mom_bull = ret_short > dyn_threshold
            mom_bear = ret_short < -dyn_threshold
            vshort_bull = ret_vshort > dyn_threshold * 0.7
            vshort_bear = ret_vshort < -dyn_threshold * 0.7

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
            bb_compressed = bb_pctile < BB_COMPRESS_PCTILE

            bull_votes = sum(
                [mom_bull, vshort_bull, ema_bull, rsi_bull, macd_bull, bb_compressed]
            )
            bear_votes = sum(
                [mom_bear, vshort_bear, ema_bear, rsi_bear, macd_bear, bb_compressed]
            )

            btc_confirm = True
            if symbol != "BTC":
                if bull_votes >= MIN_VOTES and self.btc_momentum < BTC_OPPOSE_THRESHOLD:
                    btc_confirm = False
                if (
                    bear_votes >= MIN_VOTES
                    and self.btc_momentum > -BTC_OPPOSE_THRESHOLD
                ):
                    btc_confirm = False

            bullish = bull_votes >= MIN_VOTES and btc_confirm
            bearish = bear_votes >= MIN_VOTES and btc_confirm

            in_cooldown = (
                self.bar_count - self.exit_bar.get(symbol, -999)
            ) < COOLDOWN_BARS

            vol_scale = 1.0
            weight = SYMBOL_WEIGHTS.get(symbol, 0.33)
            if high_corr and symbol == "SOL":
                weight *= 0.5
            mom_strength = abs(ret_short) / dyn_threshold
            strength_scale = 1.0
            size = (
                equity
                * BASE_POSITION_PCT
                * weight
                * vol_scale
                * strength_scale
                * dd_scale
            )

            funding_rates = bd.history["funding_rate"].values[-FUNDING_LOOKBACK:]
            avg_funding = (
                np.mean(funding_rates)
                if len(funding_rates) >= FUNDING_LOOKBACK
                else 0.0
            )

            current_pos = portfolio.positions.get(symbol, 0.0)
            target = current_pos

            if current_pos == 0:
                if not in_cooldown:
                    funding_mult = 1.0
                    if bullish:
                        if avg_funding < 0:
                            funding_mult = 1.0 + FUNDING_BOOST
                        target = size * funding_mult
                        self.pyramided[symbol] = False
                    elif bearish:
                        if avg_funding > 0:
                            funding_mult = 1.0 + FUNDING_BOOST
                        target = -size * funding_mult
                        self.pyramided[symbol] = False
            else:
                if symbol in self.entry_prices and not self.pyramided.get(symbol, True):
                    entry = self.entry_prices[symbol]
                    pnl = (mid - entry) / entry
                    if current_pos < 0:
                        pnl = -pnl
                    if pnl > PYRAMID_THRESHOLD:
                        if current_pos > 0 and bullish:
                            target = current_pos + size * PYRAMID_SIZE
                            self.pyramided[symbol] = True
                        elif current_pos < 0 and bearish:
                            target = current_pos - size * PYRAMID_SIZE
                            self.pyramided[symbol] = True

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

                if symbol in self.entry_prices:
                    entry = self.entry_prices[symbol]
                    pnl = (mid - entry) / entry
                    if current_pos < 0:
                        pnl = -pnl
                    if pnl > TAKE_PROFIT_PCT:
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


def _load_params_from_config():
    """Load strategy parameters from JSON config file.

    If config file exists and contains valid JSON, update module-level constants.
    Parameters that should be integers are cast to int type.
    Errors are handled silently to preserve default values.
    """
    config_path = (
        Path(__file__).resolve().parent.parent / "config" / "optimized_params.json"
    )

    INT_PARAMS = {
        "SHORT_WINDOW",
        "MED_WINDOW",
        "MED2_WINDOW",
        "LONG_WINDOW",
        "EMA_FAST",
        "EMA_SLOW",
        "RSI_PERIOD",
        "RSI_BULL",
        "RSI_BEAR",
        "RSI_OVERBOUGHT",
        "RSI_OVERSOLD",
        "MACD_FAST",
        "MACD_SLOW",
        "MACD_SIGNAL",
        "BB_PERIOD",
        "FUNDING_LOOKBACK",
        "VOL_LOOKBACK",
        "ATR_LOOKBACK",
        "COOLDOWN_BARS",
        "MIN_VOTES",
        "CORR_LOOKBACK",
    }

    try:
        if config_path.exists():
            with open(config_path, "r") as f:
                params = json.load(f)

            for key, value in params.items():
                if key in globals():
                    if key in INT_PARAMS:
                        value = int(value)
                    globals()[key] = value
    except (FileNotFoundError, json.JSONDecodeError, TypeError, KeyError):
        pass


_load_params_from_config()
