import numpy as np
from typing import Dict, List, Optional
import pandas as pd

from config import get_settings


class Indicators:
    def __init__(self):
        self.settings = get_settings()

    @staticmethod
    def ema(values: np.ndarray, span: int) -> np.ndarray:
        alpha = 2.0 / (span + 1)
        result = np.empty_like(values, dtype=float)
        result[0] = values[0]
        for i in range(1, len(values)):
            result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
        return result

    @staticmethod
    def calc_rsi(closes: np.ndarray, period: int) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes[-(period + 1) :])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        rs = avg_gain / max(avg_loss, 1e-10)
        return float(100 - 100 / (1 + rs))

    @staticmethod
    def calc_atr(
        highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, lookback: int
    ) -> Optional[float]:
        if len(highs) < lookback + 1:
            return None
        tr = np.maximum(
            highs[-lookback:] - lows[-lookback:],
            np.maximum(
                np.abs(highs[-lookback:] - closes[-(lookback + 1) : -1]),
                np.abs(lows[-lookback:] - closes[-(lookback + 1) : -1]),
            ),
        )
        return float(np.mean(tr))

    @staticmethod
    def calc_macd_histogram(
        closes: np.ndarray, fast: int, slow: int, signal: int
    ) -> float:
        min_len = slow + signal + 5
        if len(closes) < min_len:
            return 0.0

        fast_ema = Indicators.ema(closes[-min_len:], fast)
        slow_ema = Indicators.ema(closes[-min_len:], slow)
        macd_line = fast_ema - slow_ema
        signal_line = Indicators.ema(macd_line, signal)
        return macd_line[-1] - signal_line[-1]

    @staticmethod
    def calc_bb_width_percentile(closes: np.ndarray, period: int) -> float:
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
        percentile = 100 * np.sum(np.array(widths) <= current_width) / len(widths)
        return percentile

    @staticmethod
    def calc_volatility(closes: np.ndarray, lookback: int) -> float:
        if len(closes) < lookback:
            return 0.015
        log_rets = np.diff(np.log(closes[-lookback:]))
        return max(float(np.std(log_rets)), 1e-6)

    @staticmethod
    def calc_correlation(
        closes1: np.ndarray, closes2: np.ndarray, lookback: int
    ) -> float:
        if len(closes1) < lookback or len(closes2) < lookback:
            return 0.5

        rets1 = np.diff(np.log(closes1[-lookback:]))
        rets2 = np.diff(np.log(closes2[-lookback:]))

        if len(rets1) < 10 or len(rets2) < 10:
            return 0.5

        corr = np.corrcoef(rets1, rets2)[0, 1]
        return corr if not np.isnan(corr) else 0.5

    @staticmethod
    def calc_returns(closes: np.ndarray, window: int) -> float:
        if len(closes) < window + 1:
            return 0.0
        return (closes[-1] - closes[-window]) / closes[-window]
