"""
Upbit 현물 전용 전략. exp430: val 구간(2023-01~2024-06) 재최적화 (val score 3.849)

핵심 변경 (exp420 대비):
  - EMA(48/100) — FAST 19→48
  - TREND_FILTER_BARS 200→339
  - SMA(339) 필터 (1.005 배수 제거)
  - SMA 기울기 임계값 0.035%→0.012%
  - ADX(24) > 18 (15→18)
  - ADX<8 추세 약화 청산 (10→8)
  - RSI(11) 40/53 비대칭 (9/45/46)
  - MACD(10/16/9) (8/17/9)
  - MAX_HOLD=60봉 (98)
  - ATR*3.0 trailing stop (4.15)
  - entry_stop 1.2xATR (1.9)
  - VOL_LOOKBACK=26 (28)

진입: EMA(48) > EMA(100) AND 현재가 > SMA(339) AND SMA339 기울기>0.012%
      AND ADX(24) > 18 AND stoch_rsi > 30 AND aux_bull >= 2
청산: EMA(48) < EMA(100) OR aux_bear >= 4/5 OR 보유기간 >= 60봉 OR ATR trailing stop
포지션: 99% (변동성 역비례 스케일링)
"""

import numpy as np
from upbit_prepare import UpbitSignal, UpbitPortfolioState, UpbitBarData

ACTIVE_SYMBOLS    = ["KRW-BTC"]
SYMBOL_WEIGHTS    = {"KRW-BTC": 1.0}

EMA_FAST          = 48
EMA_SLOW          = 100
RSI_PERIOD        = 11
RSI_BULL          = 40
RSI_BEAR          = 53
MACD_FAST         = 10
MACD_SLOW         = 16
MACD_SIGNAL       = 9
MED_WINDOW        = 12

TREND_FILTER_BARS = 339
BASE_POSITION_PCT = 0.99
BASE_THRESHOLD    = 0.015
VOL_LOOKBACK      = 26
TARGET_VOL        = 0.015
COOLDOWN_BARS     = 24
MIN_BULL_VOTES    = 2
MIN_BEAR_VOTES    = 3
ATR_STOP_MULT     = 3.0


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


MAX_HOLD_BARS     = 60

ENTRY_STOP_MULT   = 1.2

class Strategy:
    def __init__(self) -> None:
        self.exit_bar: dict[str, int] = {}
        self.entry_bar: dict[str, int] = {}
        self.peak_price: dict[str, float] = {}
        self.entry_price: dict[str, float] = {}
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
            above_trend  = mid > sma_long * 1.000  # SMA200 0.5% 이상
            sma_slope    = (sma_long - sma_prev) / max(sma_prev, 1.0)
            sma_rising   = sma_slope > 0.00012  # SMA200 0.035% 이상 상승 중

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
            stoch_rsi = _calc_stoch_rsi(closes, RSI_PERIOD)  # 진입: stoch_rsi > 30, 청산: stoch_rsi < 40
            macd_h   = _calc_macd(closes)
            adx, plus_di, minus_di = _calc_adx(bd.history, period=24)
            strong_trend = adx > 18.0

            # ATR trailing stop 계산
            df_atr = bd.history.iloc[-30:]
            h_atr  = df_atr["high"].values.astype(float)
            l_atr  = df_atr["low"].values.astype(float)
            c_atr  = df_atr["close"].values.astype(float)
            tr_arr = np.maximum(h_atr[1:] - l_atr[1:],
                     np.maximum(np.abs(h_atr[1:] - c_atr[:-1]),
                                np.abs(l_atr[1:]  - c_atr[:-1])))
            atr_val = float(np.mean(tr_arr[-14:]))

            # 부가 신호 3개 (EMA 제외)
            aux_bull = sum([
                ret_med > dyn_threshold,
                rsi > RSI_BULL,
                macd_h > 0,
            ])
            # 부가 신호 5개 - 청산에는 4/5 필요
            recent_high = float(np.max(closes[-3:]))
            below_recent_high = mid < recent_high * 0.992
            aux_bear = sum([
                ret_med < -dyn_threshold,
                rsi < RSI_BEAR,
                macd_h < 0,
                stoch_rsi < 40,
                below_recent_high,
            ])

            in_cooldown = (self.bar_count - self.exit_bar.get(symbol, -999)) < COOLDOWN_BARS

            current_pos = portfolio.positions.get(symbol, 0.0)
            target = current_pos

            hold_bars = self.bar_count - self.entry_bar.get(symbol, self.bar_count)
            if current_pos == 0:
                if ema_bull and above_trend and sma_rising and strong_trend and stoch_rsi > 30 and aux_bull >= MIN_BULL_VOTES and not in_cooldown:
                    # 변동성 역비례 포지션 사이징 (고변동성일수록 작은 포지션)
                    pos_scale = float(np.clip(1.0 / max(vol_ratio, 1e-10), 0.7, 1.0))
                    target = equity * BASE_POSITION_PCT * pos_scale
                    self.entry_bar[symbol] = self.bar_count
                    self.peak_price[symbol] = mid
                    self.entry_price[symbol] = mid
            else:
                # 최고가 갱신 및 ATR trailing/entry stop
                self.peak_price[symbol] = max(self.peak_price.get(symbol, mid), mid)
                trailing_stop   = self.peak_price[symbol] - ATR_STOP_MULT * atr_val
                entry_stop      = self.entry_price.get(symbol, 0.0) - ENTRY_STOP_MULT * atr_val
                atr_stop_hit    = mid < trailing_stop or mid < entry_stop
                adx_weak        = adx < 8.0  # 추세 약화 청산
                time_exit = hold_bars >= MAX_HOLD_BARS
                if ema_bear or aux_bear >= 4 or time_exit or atr_stop_hit or adx_weak:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(UpbitSignal(symbol=symbol, target_position=target))
                if target == 0:
                    self.exit_bar[symbol] = self.bar_count

        return signals
