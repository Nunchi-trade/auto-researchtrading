"""
Equities momentum ensemble strategy with ML confidence gate.
Phase 2: GradientBoosting model trained on warmup bars filters ensemble signals.

5-signal ensemble: momentum, EMA crossover, RSI, MACD, BB compression.
3/5 majority vote for entries. ATR trailing stop for exits.
ML model gates low-confidence signals after warmup period.
"""

import numpy as np
from scipy.stats import linregress
from sklearn.ensemble import GradientBoostingClassifier
from prepare import Signal, PortfolioState, BarData

ACTIVE_SYMBOLS = ["SPY", "QQQ", "IWM", "XLE", "XLF", "TLT", "AAPL", "NVDA", "JPM", "UNH"]

SHORT_WINDOW = 5
MED_WINDOW = 10
LONG_WINDOW = 20
EMA_FAST = 10
EMA_SLOW = 30
RSI_PERIOD = 5
RSI_BULL = 50
RSI_BEAR = 50
RSI_OVERBOUGHT = 65
RSI_OVERSOLD = 35

MACD_FAST = 8
MACD_SLOW = 17
MACD_SIGNAL = 9

BB_PERIOD = 20

BASE_POSITION_PCT = 0.08
VOL_LOOKBACK = 20
TARGET_VOL = 0.01
ATR_LOOKBACK = 14
ATR_STOP_MULT = 3.0
TAKE_PROFIT_PCT = 99.0
BASE_THRESHOLD = 0.01

COOLDOWN_BARS = 1
MIN_VOTES = 3

# ML parameters
ML_WARMUP_BARS = 150
ML_FORWARD_BARS = 5
ML_FORWARD_THRESHOLD = 0.002
CONFIDENCE_THRESHOLD = 0.35
ML_N_ESTIMATORS = 100
ML_MAX_DEPTH = 3
ML_MIN_SAMPLES_LEAF = 10


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
        # ML state
        self.model = None
        self.trained = False
        self.feature_buffer = []
        self.label_buffer = []
        # Store recent closes per symbol for label generation
        self._recent_closes = {}

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

    def _extract_features(self, closes, highs, lows, volumes, atr_val, rsi_val, macd_val, bb_pctile):
        """Extract ~28 features from history arrays. Returns numpy array."""
        n = len(closes)
        features = []

        # Momentum: returns over multiple windows
        for w in [5, 10, 20]:
            if n > w:
                features.append((closes[-1] - closes[-w]) / closes[-w])
            else:
                features.append(0.0)
        if n > 60:
            features.append((closes[-1] - closes[-60]) / closes[-60])
        else:
            features.append(0.0)

        # Trend: EMA spread normalized
        if n > EMA_SLOW + 10:
            ema_f = ema(closes[-(EMA_SLOW + 10):], EMA_FAST)
            ema_s = ema(closes[-(EMA_SLOW + 10):], EMA_SLOW)
            features.append((ema_f[-1] - ema_s[-1]) / closes[-1])
        else:
            features.append(0.0)
        # Price vs SMA(50)
        if n >= 50:
            sma50 = np.mean(closes[-50:])
            features.append((closes[-1] - sma50) / sma50)
        else:
            features.append(0.0)

        # RSI: current RSI(5), RSI(14), RSI delta
        features.append(rsi_val / 100.0)
        rsi14 = calc_rsi(closes, 14) / 100.0
        features.append(rsi14)
        if n > 5:
            rsi_prev = calc_rsi(closes[:-5], RSI_PERIOD) / 100.0
            features.append(rsi_val / 100.0 - rsi_prev)
        else:
            features.append(0.0)

        # MACD: histogram normalized, line
        features.append(macd_val / closes[-1] if closes[-1] > 0 else 0.0)
        if n > MACD_SLOW + MACD_SIGNAL + 5:
            fast_e = ema(closes[-(MACD_SLOW + MACD_SIGNAL + 5):], MACD_FAST)
            slow_e = ema(closes[-(MACD_SLOW + MACD_SIGNAL + 5):], MACD_SLOW)
            macd_line = (fast_e[-1] - slow_e[-1]) / closes[-1]
            features.append(macd_line)
        else:
            features.append(0.0)

        # Volatility: vol(10d), vol(20d), vol ratio, ATR/close, vol percentile
        vol10 = self._calc_vol(closes, 10)
        vol20 = self._calc_vol(closes, 20)
        features.append(vol10)
        features.append(vol20)
        features.append(vol10 / max(vol20, 1e-8))
        features.append(atr_val / closes[-1] if atr_val and closes[-1] > 0 else 0.0)
        # Vol percentile: where current 10d vol sits vs 60-bar history
        if n > 60:
            vols = [self._calc_vol(closes[:i], 10) for i in range(max(11, n - 60), n)]
            if vols:
                features.append(np.sum(np.array(vols) <= vol10) / len(vols))
            else:
                features.append(0.5)
        else:
            features.append(0.5)

        # Volume: ratio vs 20d avg, volume trend
        if len(volumes) >= 20:
            vol_avg = np.mean(volumes[-20:])
            features.append(volumes[-1] / max(vol_avg, 1) if vol_avg > 0 else 1.0)
            vol_5avg = np.mean(volumes[-5:])
            features.append(vol_5avg / max(vol_avg, 1))
        else:
            features.append(1.0)
            features.append(1.0)

        # Price action: range/ATR, upper shadow, lower shadow, gap
        if len(highs) > 1 and len(lows) > 1:
            bar_range = highs[-1] - lows[-1]
            features.append(bar_range / max(atr_val, 1e-8) if atr_val else 0.0)
            body = abs(closes[-1] - closes[-2]) if len(closes) > 1 else 0
            features.append((highs[-1] - max(closes[-1], closes[-2] if len(closes) > 1 else closes[-1])) / max(bar_range, 1e-8))
            features.append((min(closes[-1], closes[-2] if len(closes) > 1 else closes[-1]) - lows[-1]) / max(bar_range, 1e-8))
            # Gap
            if len(closes) > 1:
                features.append((closes[-1] - closes[-2]) / closes[-2])
            else:
                features.append(0.0)
        else:
            features.extend([0.0, 0.0, 0.0, 0.0])

        # Bollinger: width, position, percentile
        features.append(bb_pctile / 100.0)
        if n >= BB_PERIOD:
            sma = np.mean(closes[-BB_PERIOD:])
            std = np.std(closes[-BB_PERIOD:])
            if std > 0:
                features.append((closes[-1] - sma) / (2 * std))  # position in bands [-1, 1]
                features.append(2 * std / sma)  # width
            else:
                features.extend([0.0, 0.0])
        else:
            features.extend([0.0, 0.0])

        # Regression: 20-bar slope and R-squared
        if n >= 20:
            x = np.arange(20)
            slope, _, r_value, _, _ = linregress(x, closes[-20:])
            features.append(slope / closes[-1])  # normalized slope
            features.append(r_value ** 2)  # R-squared
        else:
            features.extend([0.0, 0.0])

        return np.array(features, dtype=float)

    def _train_model(self):
        """Train gradient boosting classifier on accumulated feature/label data."""
        if len(self.feature_buffer) < 50:
            return
        X = np.array(self.feature_buffer)
        y = np.array(self.label_buffer)
        # Need both classes present
        if len(np.unique(y)) < 2:
            return
        self.model = GradientBoostingClassifier(
            n_estimators=ML_N_ESTIMATORS,
            max_depth=ML_MAX_DEPTH,
            min_samples_leaf=ML_MIN_SAMPLES_LEAF,
            learning_rate=0.1,
            subsample=0.8,
        )
        self.model.fit(X, y)
        self.trained = True

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
            highs = bd.history["high"].values
            lows = bd.history["low"].values
            volumes = bd.history["volume"].values
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

            # ML: extract features and either accumulate or predict
            atr_val = self._calc_atr(bd.history, ATR_LOOKBACK) or mid * 0.02
            features = self._extract_features(
                closes, highs, lows, volumes, atr_val, rsi, macd_hist, bb_pctile
            )

            # During warmup: accumulate training data with forward-looking labels
            if self.bar_count <= ML_WARMUP_BARS:
                # Store closes for forward label computation
                if symbol not in self._recent_closes:
                    self._recent_closes[symbol] = []
                self._recent_closes[symbol].append(mid)

                # Generate label from previous features (we need forward returns)
                if len(self._recent_closes[symbol]) > ML_FORWARD_BARS:
                    past_close = self._recent_closes[symbol][-ML_FORWARD_BARS - 1]
                    forward_ret = (mid - past_close) / past_close
                    label = 1 if forward_ret > ML_FORWARD_THRESHOLD else 0
                    self.feature_buffer.append(features)
                    self.label_buffer.append(label)

            # Train at end of warmup
            if self.bar_count == ML_WARMUP_BARS + 1 and not self.trained:
                self._train_model()

            # ML as 6th vote in ensemble (FIXED: add vote before bullish/bearish check)
            if self.trained:
                try:
                    ml_confidence = self.model.predict_proba(features.reshape(1, -1))[0][1]
                    ml_bull = ml_confidence > 0.55
                    ml_bear = ml_confidence < 0.45
                    bull_votes += int(ml_bull)
                    bear_votes += int(ml_bear)
                except Exception:
                    pass

            bullish = bull_votes >= MIN_VOTES
            bearish = bear_votes >= MIN_VOTES

            in_cooldown = (
                self.bar_count - self.exit_bar.get(symbol, -999)
            ) < COOLDOWN_BARS

            inv_vol_scale = min(TARGET_VOL / realized_vol, 3.0)
            size = equity * BASE_POSITION_PCT * dd_scale * inv_vol_scale

            # No ML-based sizing — let ensemble + ML vote handle entry quality

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
                atr = atr_val

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
                    self.atr_at_entry[symbol] = atr_val
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
                    self.atr_at_entry[symbol] = atr_val
                    self.pyramided[symbol] = False

        return signals
