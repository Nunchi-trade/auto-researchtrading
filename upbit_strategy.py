"""
Upbit 현물 전용 전략. exp325: 모멘텀 로그 수익률 변경 (score 5.063)

핵심 발견:
  1. EMA(19/100) 크로스오버
  2. SMA(200)*1.005 필터 + 0.04% 이상 상승 기울기 (8봉 비교)
  3. ADX(25) > 15 - 추세 강도 필터
  4. COOLDOWN=24봉 - 재진입 대기
  5. RSI(9) 45/46 비대칭
  6. MACD(8/17/9)
  7. MAX_HOLD=96봉
  8. VOL_LOOKBACK=28

진입: EMA(19) > EMA(100) AND 현재가 > SMA(200)*1.005 AND SMA200 기울기>0.04%
      AND ADX(25) > 15 AND aux_bull >= 2
청산: EMA(19) < EMA(100) OR aux_bear >= 3 OR 보유기간 >= 96봉
포지션: 99%
"""

import numpy as np
from upbit_prepare import UpbitSignal, UpbitPortfolioState, UpbitBarData

ACTIVE_SYMBOLS    = ["KRW-BTC"]
SYMBOL_WEIGHTS    = {"KRW-BTC": 1.0}

EMA_FAST          = 19
EMA_SLOW          = 100
RSI_PERIOD        = 9
RSI_BULL          = 45
RSI_BEAR          = 46
MACD_FAST         = 9
MACD_SLOW         = 17
MACD_SIGNAL       = 9
MED_WINDOW        = 12

TREND_FILTER_BARS = 200
BASE_POSITION_PCT = 0.99
BASE_THRESHOLD    = 0.015
VOL_LOOKBACK      = 28
TARGET_VOL        = 0.015
COOLDOWN_BARS     = 24
MIN_BULL_VOTES    = 2
MIN_BEAR_VOTES    = 3


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    result = np.empty_like(values, dtype=float)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


def _calc_stoch_rsi(closes: np.ndarray, rsi_period: int = 8, stoch_period: int = 14) -> float:
    """Stochastic RSI — RSI의 상대적 위치 (0~100)."""
    need = rsi_period + stoch_period + 1
    if len(closes) < need:
        return 50.0
    rsi_series = np.array([_calc_rsi(closes[:-(need - 1 - i)] if need - 1 - i > 0 else closes, rsi_period)
                            for i in range(stoch_period)])
    lo, hi = float(np.min(rsi_series)), float(np.max(rsi_series))
    if hi - lo < 1e-8:
        return 50.0
    current_rsi = _calc_rsi(closes, rsi_period)
    return 100.0 * (current_rsi - lo) / (hi - lo)


def _calc_rsi(closes: np.ndarray, period: int) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    rs = np.mean(gains) / max(np.mean(losses), 1e-10)
    return 100 - 100 / (1 + rs)


def _calc_adx(history_df, period: int = 14) -> tuple[float, float, float]:
    """Average Directional Index — (adx, +DI, -DI)."""
    need = period * 3
    if len(history_df) < need:
        return 0.0, 0.0, 0.0
    df = history_df.iloc[-need:]
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)

    prev_close = close[:-1]
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - prev_close),
                    np.abs(low[1:]  - prev_close)))
    plus_dm  = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                        np.maximum(high[1:] - high[:-1], 0.0), 0.0)
    minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                        np.maximum(low[:-1] - low[1:], 0.0), 0.0)

    atr      = _ema(tr,       period)
    plus_di  = 100.0 * _ema(plus_dm,  period) / np.maximum(atr, 1e-10)
    minus_di = 100.0 * _ema(minus_dm, period) / np.maximum(atr, 1e-10)
    dx = 100.0 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-10)
    adx = _ema(dx, period)
    return float(adx[-1]), float(plus_di[-1]), float(minus_di[-1])


def _calc_macd(closes: np.ndarray) -> float:
    if len(closes) < MACD_SLOW + MACD_SIGNAL + 5:
        return 0.0
    buf = closes[-(MACD_SLOW + MACD_SIGNAL + 5):]
    macd_line   = _ema(buf, MACD_FAST) - _ema(buf, MACD_SLOW)
    signal_line = _ema(macd_line, MACD_SIGNAL)
    return float(macd_line[-1] - signal_line[-1])


MAX_HOLD_BARS     = 96

class Strategy:
    def __init__(self) -> None:
        self.exit_bar: dict[str, int] = {}
        self.entry_bar: dict[str, int] = {}
        self.bar_count = 0

    def on_bar(self, bar_data: dict, portfolio: UpbitPortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        self.bar_count += 1

        min_bars = max(TREND_FILTER_BARS, EMA_SLOW + 20, MACD_SLOW + MACD_SIGNAL + 5) + 1

        for symbol in ACTIVE_SYMBOLS:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < min_bars:
                continue

            closes = bd.history["close"].values
            mid    = bd.close

            buf   = closes[-(EMA_SLOW + 20):]
            ema_f = _ema(buf, EMA_FAST)
            ema_s = _ema(buf, EMA_SLOW)
            ema_bull = ema_f[-1] > ema_s[-1]
            ema_bear = ema_f[-1] < ema_s[-1]

            sma_long     = float(np.mean(closes[-TREND_FILTER_BARS:]))
            sma_prev     = float(np.mean(closes[-(TREND_FILTER_BARS + 8):-8]))
            above_trend  = mid > sma_long * 1.005  # SMA200 0.5% 이상
            sma_slope    = (sma_long - sma_prev) / max(sma_prev, 1.0)
            sma_rising   = sma_slope > 0.0004  # SMA200 0.04% 이상 상승 중

            # 동적 임계값
            if len(closes) >= VOL_LOOKBACK:
                log_rets     = np.diff(np.log(closes[-VOL_LOOKBACK:]))
                realized_vol = max(float(np.std(log_rets)), 1e-6)
            else:
                realized_vol = TARGET_VOL
            vol_ratio     = realized_vol / TARGET_VOL
            dyn_threshold = float(np.clip(BASE_THRESHOLD * (0.3 + vol_ratio * 0.7), 0.005, 0.020))

            ret_med   = float(np.log(closes[-1] / closes[-MED_WINDOW]))
            rsi       = _calc_rsi(closes, RSI_PERIOD)
            stoch_rsi = _calc_stoch_rsi(closes, RSI_PERIOD)
            macd_h   = _calc_macd(closes)
            adx, plus_di, minus_di = _calc_adx(bd.history, period=25)
            strong_trend = adx > 15.0

            # 부가 신호 3개 (EMA 제외)
            aux_bull = sum([
                ret_med > dyn_threshold,
                rsi > RSI_BULL,
                macd_h > 0,
            ])
            aux_bear = sum([
                ret_med < -dyn_threshold,
                rsi < RSI_BEAR,
                macd_h < 0,
            ])

            in_cooldown = (self.bar_count - self.exit_bar.get(symbol, -999)) < COOLDOWN_BARS

            current_pos = portfolio.positions.get(symbol, 0.0)
            target = current_pos

            hold_bars = self.bar_count - self.entry_bar.get(symbol, self.bar_count)
            if current_pos == 0:
                if ema_bull and above_trend and sma_rising and strong_trend and aux_bull >= MIN_BULL_VOTES and not in_cooldown:
                    target = equity * BASE_POSITION_PCT
                    self.entry_bar[symbol] = self.bar_count
            else:
                time_exit = hold_bars >= MAX_HOLD_BARS
                if ema_bear or aux_bear >= MIN_BEAR_VOTES or time_exit:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(UpbitSignal(symbol=symbol, target_position=target))
                if target == 0:
                    self.exit_bar[symbol] = self.bar_count

        return signals
