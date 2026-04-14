import pytest
import pandas as pd

from upbit_prepare import UpbitBarData, UpbitPortfolioState
from upbit_mtf_strategy import DEFAULT_MTF_PARAMS, MultiTimeframeStrategy


def test_default_mtf_params_match_current_dd15_candidate():
    assert DEFAULT_MTF_PARAMS["FULL_LONG_PCT"] == 0.92
    assert DEFAULT_MTF_PARAMS["REDUCED_PCT"] == 0.576
    assert DEFAULT_MTF_PARAMS["REDUCED_HIGH_PCT"] == 0.576
    assert DEFAULT_MTF_PARAMS["REDUCED_LOW_PCT"] == 0.00
    assert DEFAULT_MTF_PARAMS["MACRO_FULL_THRESHOLD"] == 0.58
    assert DEFAULT_MTF_PARAMS["MACRO_REDUCED_THRESHOLD"] == 0.55
    assert DEFAULT_MTF_PARAMS["MICRO_FULL_THRESHOLD"] == 0.50
    assert DEFAULT_MTF_PARAMS["MICRO_ENTER_FULL_THRESHOLD"] == 0.52
    assert DEFAULT_MTF_PARAMS["MICRO_EXIT_FULL_THRESHOLD"] == 0.46
    assert DEFAULT_MTF_PARAMS["MICRO_REDUCED_THRESHOLD"] == 0.40
    assert DEFAULT_MTF_PARAMS["MAX_MACRO_DRAWDOWN"] == 0.07
    assert DEFAULT_MTF_PARAMS["STATE_CONFIRM_BARS"] == 4
    assert DEFAULT_MTF_PARAMS["MIN_STATE_HOLD_BARS"] == 1
    assert DEFAULT_MTF_PARAMS["MIN_REBALANCE_FRACTION"] == 0.12


def _make_interval_df(interval_minutes: int, closes: list[float]) -> pd.DataFrame:
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "timestamp": index * interval_minutes * 60_000,
                "open": close * 0.998,
                "high": close * 1.002,
                "low": close * 0.996,
                "close": close,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(rows)


def _build_interval_data(
    *,
    macro_closes: list[float],
    micro_closes: dict[int, list[float]],
) -> dict[int, dict[str, pd.DataFrame]]:
    interval_data = {240: {"KRW-BTC": _make_interval_df(240, macro_closes)}}
    for interval, closes in micro_closes.items():
        interval_data[interval] = {"KRW-BTC": _make_interval_df(interval, closes)}
    return interval_data


def _make_bar(df: pd.DataFrame) -> UpbitBarData:
    row = df.iloc[-1]
    return UpbitBarData(
        symbol="KRW-BTC",
        timestamp=int(row["timestamp"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        history=df.tail(120).reset_index(drop=True),
    )


def test_inspect_state_returns_full_long_when_macro_and_micro_align():
    macro = [1000.0 + index * 2.0 for index in range(760)]
    micro = {
        10: [100.0 + index * 0.6 for index in range(180)],
        20: [100.0 + index * 0.6 for index in range(180)],
        30: [100.0 + index * 0.6 for index in range(180)],
        60: [100.0 + index * 0.8 for index in range(180)],
        240: macro,
    }
    interval_data = _build_interval_data(macro_closes=macro, micro_closes=micro)
    strategy = MultiTimeframeStrategy(interval_data)

    snapshot = strategy.inspect_state("KRW-BTC", int(interval_data[60]["KRW-BTC"]["timestamp"].iloc[-1]))

    assert snapshot["state"] == "full_long"
    assert snapshot["target_fraction"] == DEFAULT_MTF_PARAMS["FULL_LONG_PCT"]


def test_inspect_state_returns_reduced_high_when_macro_strong_but_micro_softens():
    macro = [1000.0 + index * 2.0 for index in range(760)]
    weak_micro = [100.0 + index * 0.9 for index in range(150)]
    weak_micro.extend([weak_micro[-1] - index * 0.7 for index in range(1, 31)])
    micro = {
        10: weak_micro,
        20: weak_micro,
        30: weak_micro,
        60: weak_micro,
        240: macro,
    }
    interval_data = _build_interval_data(macro_closes=macro, micro_closes=micro)
    strategy = MultiTimeframeStrategy(interval_data, params={**DEFAULT_MTF_PARAMS, "REDUCED_HIGH_PCT": 0.60})

    snapshot = strategy.inspect_state("KRW-BTC", int(interval_data[60]["KRW-BTC"]["timestamp"].iloc[-1]))

    assert snapshot["state"] == "reduced_high"
    assert snapshot["target_fraction"] == 0.60


def test_inspect_state_returns_reduced_low_when_macro_secondary_and_micro_confirms():
    interval_data = _make_full_long_interval_data()
    params = {
        **DEFAULT_MTF_PARAMS,
        "REDUCED_LOW_PCT": 0.35,
    }
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy._macro_snapshot = lambda symbol, timestamp: (0.56, 0.04)
    strategy._micro_snapshot = lambda symbol, timestamp: 0.45

    snapshot = strategy.inspect_state("KRW-BTC", int(interval_data[60]["KRW-BTC"]["timestamp"].iloc[-1]))

    assert snapshot["state"] == "reduced_low"
    assert snapshot["target_fraction"] == 0.35


def test_on_bar_exits_to_flat_when_macro_breaks_down():
    macro = [2000.0 - index * 1.5 for index in range(760)]
    micro = {
        10: [500.0 - index * 0.5 for index in range(180)],
        20: [500.0 - index * 0.5 for index in range(180)],
        30: [500.0 - index * 0.5 for index in range(180)],
        60: [500.0 - index * 0.6 for index in range(180)],
        240: macro,
    }
    interval_data = _build_interval_data(macro_closes=macro, micro_closes=micro)
    base_df = interval_data[60]["KRW-BTC"]
    strategy = MultiTimeframeStrategy(interval_data)
    strategy.position_state["KRW-BTC"] = "full_long"

    portfolio = UpbitPortfolioState(
        cash=40_000_000.0,
        positions={"KRW-BTC": 60_000_000.0},
        entry_prices={"KRW-BTC": float(base_df["close"].iloc[-10])},
        equity=100_000_000.0,
        timestamp=int(base_df["timestamp"].iloc[-1]),
    )

    signals = strategy.on_bar({"KRW-BTC": _make_bar(base_df)}, portfolio)

    assert len(signals) == 1
    assert signals[0].target_position == 0.0


# ---------------------------------------------------------------------------
# 턴오버 제어 테스트 (이슈 #2)
# ---------------------------------------------------------------------------

def _make_full_long_interval_data() -> dict:
    """강한 상승 추세 데이터 — inspect_state가 full_long 반환."""
    macro = [1000.0 + i * 2.0 for i in range(760)]
    micro = {
        10: [100.0 + i * 0.6 for i in range(180)],
        20: [100.0 + i * 0.6 for i in range(180)],
        30: [100.0 + i * 0.6 for i in range(180)],
        60: [100.0 + i * 0.8 for i in range(180)],
        240: macro,
    }
    return _build_interval_data(macro_closes=macro, micro_closes=micro)


def _make_reduced_interval_data() -> dict:
    """강한 매크로, 약한 마이크로 — inspect_state가 reduced_high 반환."""
    macro = [1000.0 + i * 2.0 for i in range(760)]
    weak = [100.0 + i * 0.9 for i in range(150)]
    weak.extend([weak[-1] - i * 0.7 for i in range(1, 31)])
    micro = {k: weak for k in (10, 20, 30, 60)}
    micro[240] = macro
    return _build_interval_data(macro_closes=macro, micro_closes=micro)


def _make_flat_interval_data() -> dict:
    """하락 추세 — inspect_state가 flat 반환."""
    macro = [2000.0 - i * 1.5 for i in range(760)]
    micro = {k: [500.0 - i * 0.5 for i in range(180)] for k in (10, 20, 30, 60)}
    micro[240] = macro
    return _build_interval_data(macro_closes=macro, micro_closes=micro)


def _portfolio_with_full_long(equity: float = 100_000_000.0) -> UpbitPortfolioState:
    position = equity * 0.95
    return UpbitPortfolioState(
        cash=equity - position,
        positions={"KRW-BTC": position},
        entry_prices={"KRW-BTC": 80_000_000.0},
        equity=equity,
        timestamp=0,
    )


def test_no_state_change_before_confirm_window():
    """STATE_CONFIRM_BARS=3일 때 2번 연속 reduced_high 신호로는 전환이 일어나지 않는다."""
    params = {**DEFAULT_MTF_PARAMS, "STATE_CONFIRM_BARS": 3}
    interval_data = _make_reduced_interval_data()
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "full_long"

    portfolio = _portfolio_with_full_long()
    bar = _make_bar(interval_data[60]["KRW-BTC"])

    # 1번째 reduced_high 신호
    strategy.on_bar({"KRW-BTC": bar}, portfolio)
    # 2번째 reduced_high 신호 — confirm_bars=3이므로 아직 전환 안 됨
    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert signals == [], f"Confirm window(3) 미달인데 신호 발생: {signals}"


def test_state_transitions_after_confirm_window():
    """STATE_CONFIRM_BARS=2일 때 2번 연속 reduced_high 신호 후 전환이 일어난다."""
    params = {**DEFAULT_MTF_PARAMS, "STATE_CONFIRM_BARS": 2}
    interval_data = _make_reduced_interval_data()
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "full_long"

    portfolio = _portfolio_with_full_long()
    bar = _make_bar(interval_data[60]["KRW-BTC"])

    # 1번째 reduced_high 신호 — 아직 전환 없음
    strategy.on_bar({"KRW-BTC": bar}, portfolio)
    # 2번째 reduced_high 신호 — 전환 발생
    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert len(signals) == 1, f"Confirm window(2) 충족 후 신호 없음"
    assert 0 < signals[0].target_position < portfolio.equity, "reduced 포지션이어야 함"


def test_flat_exit_ignores_confirm_window():
    """STATE_CONFIRM_BARS=5여도 flat(매크로 붕괴) 종료는 즉시 발생한다."""
    params = {**DEFAULT_MTF_PARAMS, "STATE_CONFIRM_BARS": 5}
    interval_data = _make_flat_interval_data()
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "full_long"

    base_df = interval_data[60]["KRW-BTC"]
    portfolio = UpbitPortfolioState(
        cash=40_000_000.0,
        positions={"KRW-BTC": 60_000_000.0},
        entry_prices={"KRW-BTC": float(base_df["close"].iloc[-10])},
        equity=100_000_000.0,
        timestamp=int(base_df["timestamp"].iloc[-1]),
    )

    signals = strategy.on_bar({"KRW-BTC": _make_bar(base_df)}, portfolio)

    assert len(signals) == 1, "flat 종료는 즉시여야 함"
    assert signals[0].target_position == 0.0


def test_no_rebalance_when_delta_below_threshold():
    """MIN_REBALANCE_FRACTION=0.10일 때 포지션 변화가 10% 미만이면 신호를 생성하지 않는다."""
    # full_long 상태 (FULL_LONG_PCT=0.95), 이미 0.97 보유 → delta=0.02 < 0.10
    equity = 100_000_000.0
    current_position = equity * 0.97  # 이미 가득 찬 것에 가까움

    params = {
        **DEFAULT_MTF_PARAMS,
        "FULL_LONG_PCT": 0.95,   # target = 0.95, current = 0.97 → |delta| = 0.02
        "MIN_REBALANCE_FRACTION": 0.10,
    }
    interval_data = _make_full_long_interval_data()
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "full_long"  # 이미 full_long 상태

    portfolio = UpbitPortfolioState(
        cash=equity - current_position,
        positions={"KRW-BTC": current_position},
        entry_prices={"KRW-BTC": 80_000_000.0},
        equity=equity,
        timestamp=0,
    )
    bar = _make_bar(interval_data[60]["KRW-BTC"])
    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert signals == [], f"delta < MIN_REBALANCE_FRACTION인데 신호 발생: {signals}"


def test_full_long_holds_through_borderline_reduced_signal():
    interval_data = _make_full_long_interval_data()
    params = {
        **DEFAULT_MTF_PARAMS,
        "FULL_LONG_PCT": 0.90,
        "REDUCED_PCT": 0.55,
        "REDUCED_HIGH_PCT": 0.55,
        "MICRO_FULL_THRESHOLD": 0.50,
        "MICRO_EXIT_FULL_THRESHOLD": 0.46,
        "STATE_CONFIRM_BARS": 0,
        "MIN_STATE_HOLD_BARS": 0,
    }
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "full_long"

    portfolio = UpbitPortfolioState(
        cash=10_000_000.0,
        positions={"KRW-BTC": 90_000_000.0},
        entry_prices={"KRW-BTC": 80_000_000.0},
        equity=100_000_000.0,
        timestamp=0,
    )
    bar = _make_bar(interval_data[60]["KRW-BTC"])

    strategy.inspect_state = lambda symbol, timestamp: {
        "state": "reduced_high",
        "target_fraction": 0.55,
        "macro_strength": 0.80,
        "micro_strength": 0.47,
        "macro_drawdown": 0.04,
    }

    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert signals == []
    assert strategy.position_state["KRW-BTC"] == "full_long"


def test_full_long_reduces_when_micro_breaks_exit_threshold():
    interval_data = _make_full_long_interval_data()
    params = {
        **DEFAULT_MTF_PARAMS,
        "FULL_LONG_PCT": 0.90,
        "REDUCED_PCT": 0.55,
        "REDUCED_HIGH_PCT": 0.55,
        "MICRO_FULL_THRESHOLD": 0.50,
        "MICRO_EXIT_FULL_THRESHOLD": 0.46,
        "STATE_CONFIRM_BARS": 0,
        "MIN_STATE_HOLD_BARS": 0,
    }
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "full_long"

    portfolio = UpbitPortfolioState(
        cash=10_000_000.0,
        positions={"KRW-BTC": 90_000_000.0},
        entry_prices={"KRW-BTC": 80_000_000.0},
        equity=100_000_000.0,
        timestamp=0,
    )
    bar = _make_bar(interval_data[60]["KRW-BTC"])

    strategy.inspect_state = lambda symbol, timestamp: {
        "state": "reduced_high",
        "target_fraction": 0.55,
        "macro_strength": 0.80,
        "micro_strength": 0.25,
        "macro_drawdown": 0.04,
    }

    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert len(signals) == 1
    assert signals[0].target_position == pytest.approx(55_000_000.0)
    assert strategy.position_state["KRW-BTC"] == "reduced_high"


def test_flat_enters_reduced_low_with_custom_fraction():
    interval_data = _make_full_long_interval_data()
    params = {
        **DEFAULT_MTF_PARAMS,
        "REDUCED_LOW_PCT": 0.35,
    }
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "flat"

    portfolio = UpbitPortfolioState(
        cash=100_000_000.0,
        positions={},
        entry_prices={},
        equity=100_000_000.0,
        timestamp=0,
    )
    bar = _make_bar(interval_data[60]["KRW-BTC"])

    strategy.inspect_state = lambda symbol, timestamp: {
        "state": "reduced_low",
        "target_fraction": 0.35,
        "macro_strength": 0.50,
        "micro_strength": 0.45,
        "macro_drawdown": 0.04,
    }

    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert len(signals) == 1
    assert signals[0].target_position == pytest.approx(35_000_000.0)
    assert strategy.position_state["KRW-BTC"] == "reduced_low"


def test_reduced_waits_for_stronger_micro_before_promoting_to_full_long():
    interval_data = _make_full_long_interval_data()
    params = {
        **DEFAULT_MTF_PARAMS,
        "FULL_LONG_PCT": 0.90,
        "REDUCED_PCT": 0.55,
        "REDUCED_HIGH_PCT": 0.55,
        "MICRO_FULL_THRESHOLD": 0.50,
        "MICRO_ENTER_FULL_THRESHOLD": 0.55,
        "STATE_CONFIRM_BARS": 0,
        "MIN_STATE_HOLD_BARS": 0,
    }
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "reduced_high"

    portfolio = UpbitPortfolioState(
        cash=45_000_000.0,
        positions={"KRW-BTC": 55_000_000.0},
        entry_prices={"KRW-BTC": 80_000_000.0},
        equity=100_000_000.0,
        timestamp=0,
    )
    bar = _make_bar(interval_data[60]["KRW-BTC"])

    strategy.inspect_state = lambda symbol, timestamp: {
        "state": "full_long",
        "target_fraction": 0.90,
        "macro_strength": 0.80,
        "micro_strength": 0.52,
        "macro_drawdown": 0.04,
    }

    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert signals == []
    assert strategy.position_state["KRW-BTC"] == "reduced_high"


def test_flat_enters_reduced_before_full_long_when_micro_entry_band_not_cleared():
    interval_data = _make_full_long_interval_data()
    params = {
        **DEFAULT_MTF_PARAMS,
        "FULL_LONG_PCT": 0.90,
        "REDUCED_PCT": 0.55,
        "REDUCED_HIGH_PCT": 0.55,
        "MICRO_FULL_THRESHOLD": 0.50,
        "MICRO_ENTER_FULL_THRESHOLD": 0.55,
        "STATE_CONFIRM_BARS": 0,
        "MIN_STATE_HOLD_BARS": 0,
    }
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "flat"

    portfolio = UpbitPortfolioState(
        cash=100_000_000.0,
        positions={},
        entry_prices={},
        equity=100_000_000.0,
        timestamp=0,
    )
    bar = _make_bar(interval_data[60]["KRW-BTC"])

    strategy.inspect_state = lambda symbol, timestamp: {
        "state": "full_long",
        "target_fraction": 0.90,
        "macro_strength": 0.80,
        "micro_strength": 0.52,
        "macro_drawdown": 0.04,
    }

    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert len(signals) == 1
    assert signals[0].target_position == pytest.approx(55_000_000.0)
    assert strategy.position_state["KRW-BTC"] == "reduced_high"


def test_reduced_promotes_to_full_long_after_entry_threshold_clears():
    interval_data = _make_full_long_interval_data()
    params = {
        **DEFAULT_MTF_PARAMS,
        "FULL_LONG_PCT": 0.90,
        "REDUCED_PCT": 0.55,
        "REDUCED_HIGH_PCT": 0.55,
        "MICRO_FULL_THRESHOLD": 0.50,
        "MICRO_ENTER_FULL_THRESHOLD": 0.55,
        "STATE_CONFIRM_BARS": 0,
        "MIN_STATE_HOLD_BARS": 0,
    }
    strategy = MultiTimeframeStrategy(interval_data, params=params)
    strategy.position_state["KRW-BTC"] = "reduced_high"

    portfolio = UpbitPortfolioState(
        cash=45_000_000.0,
        positions={"KRW-BTC": 55_000_000.0},
        entry_prices={"KRW-BTC": 80_000_000.0},
        equity=100_000_000.0,
        timestamp=0,
    )
    bar = _make_bar(interval_data[60]["KRW-BTC"])

    strategy.inspect_state = lambda symbol, timestamp: {
        "state": "full_long",
        "target_fraction": 0.90,
        "macro_strength": 0.80,
        "micro_strength": 0.56,
        "macro_drawdown": 0.04,
    }

    signals = strategy.on_bar({"KRW-BTC": bar}, portfolio)

    assert len(signals) == 1
    assert signals[0].target_position == pytest.approx(90_000_000.0)
    assert strategy.position_state["KRW-BTC"] == "full_long"
