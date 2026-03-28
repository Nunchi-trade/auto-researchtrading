"""
Upbit 현물 전용 전략. strategy.py(exp102) 기반.

변경사항 vs strategy.py:
- ACTIVE_SYMBOLS: KRW-BTC, KRW-ETH, KRW-SOL
- 베어리시 신호 → target = 0.0 (캐시 보유, 숏 없음)
- funding_rate 참조 완전 제거
- import: upbit_prepare에서
"""

import numpy as np
from upbit_prepare import UpbitSignal, UpbitPortfolioState, UpbitBarData

ACTIVE_SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
SYMBOL_WEIGHTS = {"KRW-BTC": 0.33, "KRW-ETH": 0.33, "KRW-SOL": 0.33}

SHORT_WINDOW  = 6
MED_WINDOW    = 12
EMA_FAST      = 7
EMA_SLOW      = 26
RSI_PERIOD    = 8
RSI_BULL      = 50
RSI_BEAR      = 50
RSI_OVERBOUGHT = 69
RSI_OVERSOLD   = 31
MACD_FAST     = 14
MACD_SLOW     = 23
MACD_SIGNAL   = 9
BB_PERIOD     = 7

BASE_POSITION_PCT = 0.08
VOL_LOOKBACK      = 36
TARGET_VOL        = 0.015
ATR_LOOKBACK      = 24
ATR_STOP_MULT     = 5.5
BASE_THRESHOLD    = 0.012
COOLDOWN_BARS     = 2
MIN_VOTES         = 4


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    result = np.empty_like(values, dtype=float)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


def _calc_rsi(closes: np.ndarray, period: int) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    rs = np.mean(gains) / max(np.mean(losses), 1e-10)
    return 100 - 100 / (1 + rs)


def _calc_atr(history, lookback: int):
    if len(history) < lookback + 1:
        return None
    highs  = history["high"].values[-lookback:]
    lows   = history["low"].values[-lookback:]
    closes = history["close"].values[-(lookback + 1):-1]
    tr = np.maximum(highs - lows,
                    np.maximum(np.abs(highs - closes), np.abs(lows - closes)))
    return float(np.mean(tr))


def _calc_macd(closes: np.ndarray) -> float:
    if len(closes) < MACD_SLOW + MACD_SIGNAL + 5:
        return 0.0
    buf = closes[-(MACD_SLOW + MACD_SIGNAL + 5):]
    macd_line   = _ema(buf, MACD_FAST) - _ema(buf, MACD_SLOW)
    signal_line = _ema(macd_line, MACD_SIGNAL)
    return float(macd_line[-1] - signal_line[-1])


def _calc_bb_width_pctile(closes: np.ndarray, period: int) -> float:
    if len(closes) < period * 3:
        return 50.0
    widths = []
    for i in range(period * 2, len(closes)):
        w = closes[i - period:i]
        sma = np.mean(w)
        width = (2 * np.std(w)) / sma if sma > 0 else 0.0
        widths.append(width)
    if len(widths) < 2:
        return 50.0
    arr = np.array(widths)
    return float(100 * np.sum(arr <= arr[-1]) / len(arr))


class Strategy:
    def __init__(self) -> None:
        self.entry_prices: dict[str, float] = {}
        self.peak_prices:  dict[str, float] = {}
        self.atr_at_entry: dict[str, float] = {}
        self.exit_bar:     dict[str, int]   = {}
        self.bar_count = 0
        self._peak_equity = 100_000_000.0

    def on_bar(self, bar_data: dict, portfolio: UpbitPortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        self.bar_count += 1
        self._peak_equity = max(self._peak_equity, equity)

        min_bars = max(EMA_SLOW, MACD_SLOW + MACD_SIGNAL + 5, BB_PERIOD * 3) + 1

        for symbol in ACTIVE_SYMBOLS:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < min_bars:
                continue

            closes = bd.history["close"].values
            mid    = bd.close

            # 동적 임계값
            if len(closes) >= VOL_LOOKBACK:
                log_rets     = np.diff(np.log(closes[-VOL_LOOKBACK:]))
                realized_vol = max(float(np.std(log_rets)), 1e-6)
            else:
                realized_vol = TARGET_VOL
            vol_ratio     = realized_vol / TARGET_VOL
            dyn_threshold = float(np.clip(BASE_THRESHOLD * (0.3 + vol_ratio * 0.7), 0.005, 0.020))

            # 6개 신호
            ret_short  = (closes[-1] - closes[-MED_WINDOW])   / closes[-MED_WINDOW]
            ret_vshort = (closes[-1] - closes[-SHORT_WINDOW])  / closes[-SHORT_WINDOW]

            ema_f = _ema(closes[-(EMA_SLOW + 10):], EMA_FAST)
            ema_s = _ema(closes[-(EMA_SLOW + 10):], EMA_SLOW)

            rsi       = _calc_rsi(closes, RSI_PERIOD)
            macd_hist = _calc_macd(closes)
            bb_pctile = _calc_bb_width_pctile(closes, BB_PERIOD)
            bb_compressed = bb_pctile < 90

            bull_votes = sum([
                ret_short  >  dyn_threshold,
                ret_vshort >  dyn_threshold * 0.7,
                ema_f[-1]  >  ema_s[-1],
                rsi > RSI_BULL,
                macd_hist > 0,
                bb_compressed,
            ])
            bear_votes = sum([
                ret_short  < -dyn_threshold,
                ret_vshort < -dyn_threshold * 0.7,
                ema_f[-1]  <  ema_s[-1],
                rsi < RSI_BEAR,
                macd_hist < 0,
                bb_compressed,
            ])

            bullish = bull_votes >= MIN_VOTES
            bearish = bear_votes >= MIN_VOTES
            in_cooldown = (self.bar_count - self.exit_bar.get(symbol, -999)) < COOLDOWN_BARS

            weight = SYMBOL_WEIGHTS.get(symbol, 0.33)
            size   = equity * BASE_POSITION_PCT * weight

            current_pos = portfolio.positions.get(symbol, 0.0)
            target = current_pos

            if current_pos == 0:
                if bullish and not in_cooldown:
                    target = size

            else:
                atr = _calc_atr(bd.history, ATR_LOOKBACK) or self.atr_at_entry.get(symbol, mid * 0.02)

                if symbol not in self.peak_prices:
                    self.peak_prices[symbol] = mid
                self.peak_prices[symbol] = max(self.peak_prices[symbol], mid)

                stop = self.peak_prices[symbol] - ATR_STOP_MULT * atr
                if mid < stop:
                    target = 0.0

                if rsi > RSI_OVERBOUGHT:
                    target = 0.0

                # 베어 신호 → 청산 (현물: 숏 진입 없음, 캐시 보유)
                if bearish and not in_cooldown:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(UpbitSignal(symbol=symbol, target_position=target))
                if target > 0 and current_pos == 0:
                    self.entry_prices[symbol]  = mid
                    self.peak_prices[symbol]   = mid
                    self.atr_at_entry[symbol]  = _calc_atr(bd.history, ATR_LOOKBACK) or mid * 0.02
                elif target == 0:
                    self.entry_prices.pop(symbol, None)
                    self.peak_prices.pop(symbol, None)
                    self.atr_at_entry.pop(symbol, None)
                    self.exit_bar[symbol] = self.bar_count

        return signals
