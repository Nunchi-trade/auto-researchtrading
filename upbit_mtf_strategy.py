from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from upbit_prepare import UpbitBarData, UpbitPortfolioState, UpbitSignal

ACTIVE_SYMBOLS = ["KRW-BTC"]
MICRO_INTERVALS = (10, 20, 30, 60, 240)
MACRO_INTERVAL = 240
MACRO_WINDOWS = (18, 30, 60, 120, 360, 720)  # 3D, 5D, 10D, 20D, 60D, 120D on 240m bars

MICRO_FAST_EMA = 8
MICRO_SLOW_EMA = 21
MICRO_BREAKOUT_LOOKBACK = 12
MICRO_MOMENTUM_LOOKBACK = 6

FULL_LONG_PCT = 0.90
REDUCED_PCT = 0.55
REDUCED_HIGH_PCT = REDUCED_PCT
REDUCED_LOW_PCT = 0.30
MACRO_FULL_THRESHOLD = 0.62
MACRO_REDUCED_THRESHOLD = 0.45
MICRO_FULL_THRESHOLD = 0.50
MICRO_ENTER_FULL_THRESHOLD = 0.54
MICRO_EXIT_FULL_THRESHOLD = 0.46
MICRO_REDUCED_THRESHOLD = 0.40
MAX_MACRO_DRAWDOWN = 0.10
MICRO_BREAKOUT_BUFFER = 0.998
MICRO_MOMENTUM_THRESHOLD = 0.0

STATE_CONFIRM_BARS = 0       # full_long<->reduced 전환에 필요한 연속 확인 봉 수
MIN_STATE_HOLD_BARS = 0      # 전환 후 최소 유지 봉 수 (flat 종료 제외)
MIN_REBALANCE_FRACTION = 0.0 # 포지션 변화 비율이 이 값 미만이면 리밸런싱 스킵

DEFAULT_MTF_PARAMS = {
    "FULL_LONG_PCT": FULL_LONG_PCT,
    "REDUCED_PCT": REDUCED_PCT,
    "REDUCED_HIGH_PCT": REDUCED_HIGH_PCT,
    "REDUCED_LOW_PCT": REDUCED_LOW_PCT,
    "MACRO_FULL_THRESHOLD": MACRO_FULL_THRESHOLD,
    "MACRO_REDUCED_THRESHOLD": MACRO_REDUCED_THRESHOLD,
    "MICRO_FULL_THRESHOLD": MICRO_FULL_THRESHOLD,
    "MICRO_ENTER_FULL_THRESHOLD": MICRO_ENTER_FULL_THRESHOLD,
    "MICRO_EXIT_FULL_THRESHOLD": MICRO_EXIT_FULL_THRESHOLD,
    "MICRO_REDUCED_THRESHOLD": MICRO_REDUCED_THRESHOLD,
    "MAX_MACRO_DRAWDOWN": MAX_MACRO_DRAWDOWN,
    "MICRO_BREAKOUT_BUFFER": MICRO_BREAKOUT_BUFFER,
    "MICRO_MOMENTUM_THRESHOLD": MICRO_MOMENTUM_THRESHOLD,
    "STATE_CONFIRM_BARS": STATE_CONFIRM_BARS,
    "MIN_STATE_HOLD_BARS": MIN_STATE_HOLD_BARS,
    "MIN_REBALANCE_FRACTION": MIN_REBALANCE_FRACTION,
}


def _merge_params(overrides: dict | None = None) -> dict:
    params = DEFAULT_MTF_PARAMS.copy()
    if overrides:
        params.update(overrides)
    return params


def _rolling_min_periods(window: int) -> int:
    return max(6, window // 6)


def _with_nan_mask(mask: pd.Series, valid: pd.Series) -> pd.Series:
    return pd.Series(np.where(valid.to_numpy(), mask.astype(float).to_numpy(), np.nan))


def _build_interval_features(interval_minutes: int, df: pd.DataFrame) -> dict[str, np.ndarray]:
    feature_df = pd.DataFrame(
        {
            "timestamp": df["timestamp"].astype(np.int64),
            "close": df["close"].astype(float),
        }
    )
    closes = feature_df["close"]
    feature_df["ema_fast"] = closes.ewm(span=MICRO_FAST_EMA, adjust=False).mean()
    feature_df["ema_slow"] = closes.ewm(span=MICRO_SLOW_EMA, adjust=False).mean()
    breakout_high = closes.rolling(MICRO_BREAKOUT_LOOKBACK, min_periods=MICRO_BREAKOUT_LOOKBACK).max().shift(1)
    feature_df["breakout_high"] = breakout_high
    feature_df["momentum"] = closes.pct_change(MICRO_MOMENTUM_LOOKBACK)

    if interval_minutes == MACRO_INTERVAL:
        for window in MACRO_WINDOWS:
            sma = closes.rolling(window, min_periods=_rolling_min_periods(window)).mean()
            rising = sma > sma.shift(3)
            feature_df[f"above_sma_{window}"] = _with_nan_mask(closes > sma, sma.notna())
            feature_df[f"sma_rising_{window}"] = _with_nan_mask(rising, sma.notna() & sma.shift(3).notna())
        rolling_high = closes.rolling(max(MACRO_WINDOWS), min_periods=12).max()
        feature_df["rolling_high"] = rolling_high

    return {
        column: feature_df[column].to_numpy()
        for column in feature_df.columns
    }


def build_feature_store(interval_data: dict[int, dict[str, pd.DataFrame]]) -> dict[int, dict[str, dict[str, np.ndarray]]]:
    store: dict[int, dict[str, dict[str, np.ndarray]]] = {}
    for interval_minutes, symbol_frames in interval_data.items():
        store[interval_minutes] = {}
        for symbol, df in symbol_frames.items():
            if df.empty:
                continue
            store[interval_minutes][symbol] = _build_interval_features(interval_minutes, df.reset_index(drop=True))
    return store


@dataclass
class StrategySnapshot:
    state: str
    target_fraction: float
    macro_strength: float
    micro_strength: float
    macro_drawdown: float


class MultiTimeframeStrategy:
    def __init__(
        self,
        interval_data: dict[int, dict[str, pd.DataFrame]],
        params: dict | None = None,
        *,
        feature_store: dict[int, dict[str, dict[str, np.ndarray]]] | None = None,
    ) -> None:
        self.interval_data = interval_data
        self.params = _merge_params(params)
        self.feature_store = feature_store or build_feature_store(interval_data)
        self.position_state: dict[str, str] = {}
        self._pending_state: dict[str, str] = {}   # 확인 대기 중인 다음 상태
        self._confirm_count: dict[str, int] = {}   # 연속 확인 카운트
        self._hold_bars: dict[str, int] = {}       # 현재 상태 유지 봉 수

    def _lookup_index(self, symbol: str, interval_minutes: int, timestamp: int) -> tuple[dict[str, np.ndarray] | None, int]:
        interval_store = self.feature_store.get(interval_minutes, {})
        symbol_store = interval_store.get(symbol)
        if not symbol_store:
            return None, -1
        timestamps = symbol_store["timestamp"]
        index = int(np.searchsorted(timestamps, timestamp, side="right") - 1)
        if index < 0:
            return None, -1
        return symbol_store, index

    def _macro_snapshot(self, symbol: str, timestamp: int) -> tuple[float, float]:
        store, index = self._lookup_index(symbol, MACRO_INTERVAL, timestamp)
        if store is None:
            return 0.0, 1.0

        positives = 0.0
        available = 0
        for window in MACRO_WINDOWS:
            for key in (f"above_sma_{window}", f"sma_rising_{window}"):
                value = float(store[key][index])
                if not np.isnan(value):
                    positives += value
                    available += 1

        close = float(store["close"][index])
        rolling_high = float(store["rolling_high"][index])
        if np.isnan(rolling_high) or rolling_high <= 0:
            drawdown = 0.0
        else:
            drawdown = max(0.0, 1.0 - close / rolling_high)

        macro_strength = positives / available if available else 0.0
        return macro_strength, drawdown

    def _micro_snapshot(self, symbol: str, timestamp: int) -> float:
        positives = 0.0
        available = 0
        breakout_buffer = float(self.params["MICRO_BREAKOUT_BUFFER"])
        momentum_threshold = float(self.params["MICRO_MOMENTUM_THRESHOLD"])

        for interval_minutes in MICRO_INTERVALS:
            store, index = self._lookup_index(symbol, interval_minutes, timestamp)
            if store is None:
                continue

            close = float(store["close"][index])
            ema_fast = float(store["ema_fast"][index])
            ema_slow = float(store["ema_slow"][index])
            breakout_high = float(store["breakout_high"][index])
            momentum = float(store["momentum"][index])

            if not np.isnan(ema_fast) and not np.isnan(ema_slow):
                positives += float(close > ema_fast > ema_slow)
                available += 1
            if not np.isnan(breakout_high):
                positives += float(close >= breakout_high * breakout_buffer)
                available += 1
            if not np.isnan(momentum):
                positives += float(momentum > momentum_threshold)
                available += 1

        return positives / available if available else 0.0

    def inspect_state(self, symbol: str, timestamp: int) -> dict[str, float | str]:
        macro_strength, macro_drawdown = self._macro_snapshot(symbol, timestamp)
        micro_strength = self._micro_snapshot(symbol, timestamp)

        macro_full = float(self.params["MACRO_FULL_THRESHOLD"])
        macro_reduced = float(self.params["MACRO_REDUCED_THRESHOLD"])
        micro_full = float(self.params["MICRO_FULL_THRESHOLD"])
        micro_reduced = float(self.params["MICRO_REDUCED_THRESHOLD"])
        max_macro_drawdown = float(self.params["MAX_MACRO_DRAWDOWN"])
        reduced_high_pct = float(self.params.get("REDUCED_HIGH_PCT", self.params["REDUCED_PCT"]))
        reduced_low_pct = float(self.params.get("REDUCED_LOW_PCT", self.params["REDUCED_PCT"]))

        state = "flat"
        target_fraction = 0.0

        if macro_drawdown > max_macro_drawdown:
            state = "flat"
        elif macro_strength >= macro_full and micro_strength >= micro_full:
            state = "full_long"
            target_fraction = float(self.params["FULL_LONG_PCT"])
        elif macro_strength >= macro_full:
            state = "reduced_high"
            target_fraction = reduced_high_pct
        elif macro_strength >= macro_reduced and micro_strength >= micro_reduced:
            state = "reduced_low"
            target_fraction = reduced_low_pct

        snapshot = StrategySnapshot(
            state=state,
            target_fraction=target_fraction,
            macro_strength=macro_strength,
            micro_strength=micro_strength,
            macro_drawdown=macro_drawdown,
        )
        return {
            "state": snapshot.state,
            "target_fraction": snapshot.target_fraction,
            "macro_strength": snapshot.macro_strength,
            "micro_strength": snapshot.micro_strength,
            "macro_drawdown": snapshot.macro_drawdown,
        }

    def on_bar(self, bar_data: dict[str, UpbitBarData], portfolio: UpbitPortfolioState) -> list[UpbitSignal]:
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        signals: list[UpbitSignal] = []

        confirm_bars = int(self.params.get("STATE_CONFIRM_BARS", 0))
        min_hold = int(self.params.get("MIN_STATE_HOLD_BARS", 0))
        min_rebalance = float(self.params.get("MIN_REBALANCE_FRACTION", 0.0))

        for symbol in ACTIVE_SYMBOLS:
            if symbol not in bar_data:
                continue

            current_position = portfolio.positions.get(symbol, 0.0)
            previous_state = self.position_state.get(symbol, "flat")
            snapshot = self.inspect_state(symbol, int(bar_data[symbol].timestamp))
            next_state = str(snapshot["state"])
            target_fraction = float(snapshot["target_fraction"])

            # Use a higher micro threshold only for promotion into full_long.
            if next_state == "full_long" and previous_state != "full_long":
                macro_full = float(self.params["MACRO_FULL_THRESHOLD"])
                micro_enter_full = float(
                    self.params.get("MICRO_ENTER_FULL_THRESHOLD", self.params["MICRO_FULL_THRESHOLD"])
                )
                if (
                    float(snapshot["macro_strength"]) >= macro_full
                    and float(snapshot["micro_strength"]) < micro_enter_full
                ):
                    next_state = "reduced_high"
                    target_fraction = float(self.params.get("REDUCED_HIGH_PCT", self.params["REDUCED_PCT"]))

            # flat 종료는 즉시 — 모든 턴오버 제어 무시
            if next_state == "flat" and current_position > 0:
                signals.append(UpbitSignal(symbol=symbol, target_position=0.0))
                self.position_state[symbol] = "flat"
                self._hold_bars[symbol] = 0
                self._confirm_count[symbol] = 0
                self._pending_state[symbol] = "flat"
                continue

            if current_position == 0.0:
                self.position_state[symbol] = "flat"
                if next_state == "flat":
                    self._pending_state[symbol] = "flat"
                    continue
                # flat → 포지션 진입 (최소 리밸런싱 체크만 적용)
                target_position = equity * target_fraction
                delta_frac = abs(target_position) / max(equity, 1.0)
                if min_rebalance > 0.0 and delta_frac < min_rebalance:
                    continue
                if abs(target_position) > 1.0:
                    signals.append(UpbitSignal(symbol=symbol, target_position=target_position))
                    self.position_state[symbol] = next_state
                    self._hold_bars[symbol] = 0
                    self._confirm_count[symbol] = 0
                    self._pending_state[symbol] = next_state
                continue

            # 포지션 보유 중 — full_long <-> reduced 전환
            # Avoid churn when macro remains strong and micro only softens slightly.
            # Require a deeper micro break before stepping down from full_long to reduced.
            if previous_state == "full_long" and next_state.startswith("reduced"):
                macro_full = float(self.params["MACRO_FULL_THRESHOLD"])
                micro_exit_full = float(
                    self.params.get("MICRO_EXIT_FULL_THRESHOLD", self.params["MICRO_FULL_THRESHOLD"])
                )
                if (
                    float(snapshot["macro_strength"]) >= macro_full
                    and float(snapshot["micro_strength"]) >= micro_exit_full
                ):
                    self._hold_bars[symbol] = self._hold_bars.get(symbol, 0) + 1
                    self._confirm_count[symbol] = 0
                    self._pending_state[symbol] = previous_state
                    continue

            if next_state == previous_state:
                # 상태 유지: hold 카운트 증가, confirm 초기화
                self._hold_bars[symbol] = self._hold_bars.get(symbol, 0) + 1
                self._confirm_count[symbol] = 0
                self._pending_state[symbol] = next_state
                continue

            # 상태 전환 시도
            # MIN_STATE_HOLD_BARS 체크
            hold = self._hold_bars.get(symbol, min_hold)
            if hold < min_hold:
                self._hold_bars[symbol] = hold + 1
                continue

            # STATE_CONFIRM_BARS 체크
            if self._pending_state.get(symbol) != next_state:
                self._pending_state[symbol] = next_state
                self._confirm_count[symbol] = 1
            else:
                self._confirm_count[symbol] = self._confirm_count.get(symbol, 0) + 1

            if self._confirm_count.get(symbol, 1) < confirm_bars:
                continue  # 확인 봉 수 부족

            # 전환 확인 완료 — MIN_REBALANCE_FRACTION 체크
            target_position = equity * target_fraction
            delta_frac = abs(target_position - current_position) / max(equity, 1.0)
            if min_rebalance > 0.0 and delta_frac < min_rebalance:
                continue

            if abs(target_position - current_position) > 1.0:
                signals.append(UpbitSignal(symbol=symbol, target_position=target_position))
                self.position_state[symbol] = next_state
                self._hold_bars[symbol] = 0
                self._confirm_count[symbol] = 0
                self._pending_state[symbol] = next_state

        return signals
