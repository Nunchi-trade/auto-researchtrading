"""
Upbit 현물 전용 전략. exp80: 하이브리드 추세 추종 (score 3.884)

핵심 발견:
  1. EMA(24/100) 크로스오버 - 진입/청산 주요 신호
  2. SMA(200) 필터 + 0.05% 이상 상승 기울기 - 상승 추세 시장만 진입
  3. COOLDOWN=24봉 - 재진입 대기로 노이즈 차단
  4. RSI 45/55 비대칭 - 진입 완화(45), 청산 엄격(55)
  5. MACD(6/13/5) - 빠른 MACD로 선행 신호

진입: EMA(24) > EMA(100) AND 현재가 > SMA(200) AND SMA200 기울기>0.05% AND aux_bull >= 2
청산: EMA(24) < EMA(100) OR aux_bear >= 3 (momentum, RSI, MACD 모두 약세)
포지션: 90%
"""

import numpy as np
from upbit_prepare import UpbitSignal, UpbitPortfolioState, UpbitBarData

ACTIVE_SYMBOLS    = ["KRW-BTC"]
SYMBOL_WEIGHTS    = {"KRW-BTC": 1.0}

EMA_FAST          = 24
EMA_SLOW          = 100
RSI_PERIOD        = 8
RSI_BULL          = 45
RSI_BEAR          = 55
MACD_FAST         = 6
MACD_SLOW         = 13
MACD_SIGNAL       = 5
MED_WINDOW        = 12

TREND_FILTER_BARS = 200
BASE_POSITION_PCT = 0.90
BASE_THRESHOLD    = 0.015
VOL_LOOKBACK      = 36
TARGET_VOL        = 0.015
COOLDOWN_BARS     = 24
MIN_BULL_VOTES    = 2   # 보조 신호 3개 중 N개 이상 강세
MIN_BEAR_VOTES    = 3   # 보조 신호 3개 전부 약세 시 청산


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


def _calc_macd(closes: np.ndarray) -> float:
    if len(closes) < MACD_SLOW + MACD_SIGNAL + 5:
        return 0.0
    buf = closes[-(MACD_SLOW + MACD_SIGNAL + 5):]
    macd_line   = _ema(buf, MACD_FAST) - _ema(buf, MACD_SLOW)
    signal_line = _ema(macd_line, MACD_SIGNAL)
    return float(macd_line[-1] - signal_line[-1])


class Strategy:
    def __init__(self) -> None:
        self.exit_bar: dict[str, int] = {}
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
            sma_prev     = float(np.mean(closes[-(TREND_FILTER_BARS + 10):-10]))
            above_trend  = mid > sma_long
            sma_slope    = (sma_long - sma_prev) / max(sma_prev, 1.0)
            sma_rising   = sma_slope > 0.0005  # SMA200 0.05% 이상 상승 중

            # 동적 임계값
            if len(closes) >= VOL_LOOKBACK:
                log_rets     = np.diff(np.log(closes[-VOL_LOOKBACK:]))
                realized_vol = max(float(np.std(log_rets)), 1e-6)
            else:
                realized_vol = TARGET_VOL
            vol_ratio     = realized_vol / TARGET_VOL
            dyn_threshold = float(np.clip(BASE_THRESHOLD * (0.3 + vol_ratio * 0.7), 0.005, 0.020))

            ret_med  = (closes[-1] - closes[-MED_WINDOW]) / closes[-MED_WINDOW]
            rsi      = _calc_rsi(closes, RSI_PERIOD)
            macd_h   = _calc_macd(closes)

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
            size = equity * BASE_POSITION_PCT

            current_pos = portfolio.positions.get(symbol, 0.0)
            target = current_pos

            if current_pos == 0:
                if ema_bull and above_trend and sma_rising and aux_bull >= MIN_BULL_VOTES and not in_cooldown:
                    target = size
            else:
                if ema_bear or aux_bear >= MIN_BEAR_VOTES:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(UpbitSignal(symbol=symbol, target_position=target))
                if target == 0:
                    self.exit_bar[symbol] = self.bar_count

        return signals
