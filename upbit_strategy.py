"""
Upbit 현물 전용 전략.

2026-04-02 balanced search 기본값:
  EMA(44/100), RSI(11) 38/52, MACD(9/16/9)
  MAX_HOLD=96, COOLDOWN=36, TFB=339
  ATR*3.0 trailing, entry_stop 1.2xATR
  SMA slope>0.02%, recent_high 4봉/0.995
  ADX(24)>18 entry, ADX<8 weak exit
  BASE_POSITION=45%, MIN_BEAR_VOTES=5
"""

import numpy as np
from upbit_prepare import UpbitSignal, UpbitPortfolioState, UpbitBarData

ACTIVE_SYMBOLS    = ["KRW-BTC"]
SYMBOL_WEIGHTS    = {"KRW-BTC": 1.0}

EMA_FAST          = 44
EMA_SLOW          = 100
RSI_PERIOD        = 11
RSI_BULL          = 38
RSI_BEAR          = 52
MACD_FAST         = 9
MACD_SLOW         = 16
MACD_SIGNAL       = 9
MED_WINDOW        = 12

TREND_FILTER_BARS = 339
SMA_SLOPE_THRESHOLD = 0.00022
ADX_ENTRY_THRESHOLD = 18.0
TREND_BOOST_MAX = 1.0
ADX_BOOST_THRESHOLD = 24.0
SLOPE_BOOST_THRESHOLD = 0.0035
BASE_POSITION_PCT = 0.45
BASE_THRESHOLD    = 0.015
VOL_LOOKBACK      = 26
TARGET_VOL        = 0.015
SIZE_TARGET_VOL   = 0.0035
MIN_POSITION_SCALE = 0.25
COOLDOWN_BARS     = 36
MIN_BULL_VOTES    = 2
MIN_BEAR_VOTES    = 5
STOCH_EXIT_THRESHOLD = 40.0
RECENT_HIGH_BUFFER = 0.995
ATR_STOP_MULT     = 3.0
MAX_HOLD_BARS     = 96

DEFAULT_STRATEGY_PARAMS = {
    "TREND_FILTER_BARS": TREND_FILTER_BARS,
    "SMA_SLOPE_THRESHOLD": SMA_SLOPE_THRESHOLD,
    "ADX_ENTRY_THRESHOLD": ADX_ENTRY_THRESHOLD,
    "TREND_BOOST_MAX": TREND_BOOST_MAX,
    "ADX_BOOST_THRESHOLD": ADX_BOOST_THRESHOLD,
    "SLOPE_BOOST_THRESHOLD": SLOPE_BOOST_THRESHOLD,
    "BASE_POSITION_PCT": BASE_POSITION_PCT,
    "SIZE_TARGET_VOL": SIZE_TARGET_VOL,
    "MIN_POSITION_SCALE": MIN_POSITION_SCALE,
    "COOLDOWN_BARS": COOLDOWN_BARS,
    "MAX_HOLD_BARS": MAX_HOLD_BARS,
    "MIN_BEAR_VOTES": MIN_BEAR_VOTES,
    "STOCH_EXIT_THRESHOLD": STOCH_EXIT_THRESHOLD,
    "RECENT_HIGH_BUFFER": RECENT_HIGH_BUFFER,
}


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


def _position_scale_from_volatility(
    realized_vol: float,
    *,
    size_target_vol: float = SIZE_TARGET_VOL,
    min_position_scale: float = MIN_POSITION_SCALE,
) -> float:
    """Keep full size in calm markets and shrink materially once hourly volatility expands."""
    vol_floor = max(realized_vol, 1e-6)
    vol_ratio = vol_floor / size_target_vol
    if vol_ratio <= 1.0:
        return 1.0
    return float(np.clip(1.0 / vol_ratio, min_position_scale, 1.0))


def _trend_position_boost(
    *,
    sma_slope: float,
    adx: float,
    aux_bull: int,
    trend_boost_max: float = TREND_BOOST_MAX,
    adx_boost_threshold: float = ADX_BOOST_THRESHOLD,
    slope_boost_threshold: float = SLOPE_BOOST_THRESHOLD,
) -> float:
    if trend_boost_max <= 1.0:
        return 1.0
    if aux_bull < 3:
        return 1.0
    if adx < adx_boost_threshold:
        return 1.0
    if sma_slope < slope_boost_threshold:
        return 1.0
    return trend_boost_max


def _merge_strategy_params(overrides: dict | None = None) -> dict:
    params = DEFAULT_STRATEGY_PARAMS.copy()
    if overrides:
        params.update(overrides)
    return params

ENTRY_STOP_MULT   = 1.2

class Strategy:
    def __init__(self, params: dict | None = None) -> None:
        self.exit_bar: dict[str, int] = {}
        self.entry_bar: dict[str, int] = {}
        self.peak_price: dict[str, float] = {}
        self.entry_price: dict[str, float] = {}
        self.bar_count = 0
        self.params = _merge_strategy_params(params)

    def on_bar(self, bar_data: dict, portfolio: UpbitPortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        self.bar_count += 1
        params = self.params
        trend_filter_bars = int(params["TREND_FILTER_BARS"])
        sma_slope_threshold = float(params["SMA_SLOPE_THRESHOLD"])
        adx_entry_threshold = float(params["ADX_ENTRY_THRESHOLD"])
        trend_boost_max = float(params["TREND_BOOST_MAX"])
        adx_boost_threshold = float(params["ADX_BOOST_THRESHOLD"])
        slope_boost_threshold = float(params["SLOPE_BOOST_THRESHOLD"])
        base_position_pct = float(params["BASE_POSITION_PCT"])
        size_target_vol = float(params["SIZE_TARGET_VOL"])
        min_position_scale = float(params["MIN_POSITION_SCALE"])
        cooldown_bars = int(params["COOLDOWN_BARS"])
        max_hold_bars = int(params["MAX_HOLD_BARS"])
        min_bear_votes = int(params["MIN_BEAR_VOTES"])
        stoch_exit_threshold = float(params["STOCH_EXIT_THRESHOLD"])
        recent_high_buffer = float(params["RECENT_HIGH_BUFFER"])

        min_bars = max(trend_filter_bars, EMA_SLOW + 20, MACD_SLOW + MACD_SIGNAL + 5) + 1

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

            sma_long     = float(np.mean(closes[-trend_filter_bars:]))
            sma_prev     = float(np.mean(closes[-(trend_filter_bars + 8):-8]))
            above_trend  = mid > sma_long * 1.000  # SMA200 0.5% 이상
            sma_slope    = (sma_long - sma_prev) / max(sma_prev, 1.0)
            sma_rising   = sma_slope > sma_slope_threshold

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
            adx, plus_di, minus_di = _calc_adx(bd.history, period=24)
            strong_trend = adx > adx_entry_threshold

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
            recent_high = float(np.max(closes[-4:]))
            below_recent_high = mid < recent_high * recent_high_buffer
            aux_bear = sum([
                ret_med < -dyn_threshold,
                rsi < RSI_BEAR,
                macd_h < 0,
                stoch_rsi < stoch_exit_threshold,
                below_recent_high,
            ])

            in_cooldown = (self.bar_count - self.exit_bar.get(symbol, -999)) < cooldown_bars

            current_pos = portfolio.positions.get(symbol, 0.0)
            target = current_pos

            hold_bars = self.bar_count - self.entry_bar.get(symbol, self.bar_count)
            if current_pos == 0:
                if ema_bull and above_trend and sma_rising and strong_trend and stoch_rsi > 25 and aux_bull >= MIN_BULL_VOTES and not in_cooldown:
                    # Reduce risk materially in volatile regimes instead of staying near full notional.
                    pos_scale = _position_scale_from_volatility(
                        realized_vol,
                        size_target_vol=size_target_vol,
                        min_position_scale=min_position_scale,
                    )
                    trend_boost = _trend_position_boost(
                        sma_slope=sma_slope,
                        adx=adx,
                        aux_bull=aux_bull,
                        trend_boost_max=trend_boost_max,
                        adx_boost_threshold=adx_boost_threshold,
                        slope_boost_threshold=slope_boost_threshold,
                    )
                    target = equity * base_position_pct * pos_scale * trend_boost
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
                time_exit = hold_bars >= max_hold_bars
                if ema_bear or aux_bear >= min_bear_votes or time_exit or atr_stop_hit or adx_weak:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(UpbitSignal(symbol=symbol, target_position=target))
                if target == 0:
                    self.exit_bar[symbol] = self.bar_count

        return signals
