import pandas as pd

from upbit_prepare import UpbitBarData, UpbitPortfolioState
from upbit_mtf_strategy import DEFAULT_MTF_PARAMS, MultiTimeframeStrategy


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


def test_inspect_state_returns_reduced_when_macro_strong_but_micro_softens():
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
    strategy = MultiTimeframeStrategy(interval_data)

    snapshot = strategy.inspect_state("KRW-BTC", int(interval_data[60]["KRW-BTC"]["timestamp"].iloc[-1]))

    assert snapshot["state"] == "reduced"
    assert snapshot["target_fraction"] == DEFAULT_MTF_PARAMS["REDUCED_PCT"]


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
