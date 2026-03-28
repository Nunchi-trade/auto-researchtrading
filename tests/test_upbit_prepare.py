# tests/test_upbit_prepare.py
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from upbit_prepare import (
    _download_upbit_candles,
    load_upbit_data,
    UpbitBarData,
    UpbitSignal,
    UpbitPortfolioState,
    SYMBOLS,
)


def _make_candle(ts_str: str, price: float) -> dict:
    return {
        "candle_date_time_utc": ts_str,
        "opening_price": price,
        "high_price": price * 1.01,
        "low_price": price * 0.99,
        "trade_price": price,
        "candle_acc_trade_volume": 10.0,
    }


def test_download_returns_dataframe_with_required_columns():
    fake_candles = [_make_candle("2024-07-01T00:00:00", 80000000.0)]
    with patch("upbit_prepare.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [fake_candles, []]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        start_ms = int(pd.Timestamp("2024-07-01", tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp("2024-07-02", tz="UTC").timestamp() * 1000)
        df = _download_upbit_candles("KRW-BTC", start_ms, end_ms)

    assert set(["timestamp", "open", "high", "low", "close", "volume"]).issubset(df.columns)
    assert len(df) == 1
    assert df["close"].iloc[0] == 80000000.0


def test_symbols_list():
    assert "KRW-BTC" in SYMBOLS


def test_upbit_bar_data_has_no_funding_rate():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(UpbitBarData)}
    assert "funding_rate" not in fields
    assert "history" in fields


import os
import tempfile


def test_load_upbit_data_returns_symbols(tmp_path, monkeypatch):
    """1분봉 parquet이 있으면 60분봉으로 리샘플링해서 반환한다."""
    monkeypatch.setattr("upbit_prepare.DATA_DIR", str(tmp_path))

    # 600개 1분봉 생성 (= 10시간 → 60분봉 10개)
    base_ms = int(pd.Timestamp("2024-07-01", tz="UTC").timestamp() * 1000)
    rows = [
        {
            "timestamp": base_ms + i * 60_000,   # 1분 간격
            "open": 80000000.0, "high": 81000000.0,
            "low": 79000000.0, "close": 80500000.0,
            "volume": 1.0,
        }
        for i in range(600)
    ]
    df = pd.DataFrame(rows)
    df.to_parquet(tmp_path / "KRW-BTC_1m.parquet", index=False)

    data = load_upbit_data("val", interval_minutes=60)
    assert "KRW-BTC" in data
    assert len(data["KRW-BTC"]) == 10  # 600분 / 60분 = 10봉


def test_load_upbit_data_skips_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr("upbit_prepare.DATA_DIR", str(tmp_path))
    data = load_upbit_data("val")
    assert data == {}


from upbit_prepare import run_upbit_backtest, compute_upbit_score, UpbitBacktestResult
import numpy as np


class _DoNothingStrategy:
    def on_bar(self, bar_data, portfolio):
        return []


class _AlwaysBuyBTC:
    def __init__(self):
        self._bought = False

    def on_bar(self, bar_data, portfolio):
        from upbit_prepare import UpbitSignal
        if not self._bought and "KRW-BTC" in bar_data:
            self._bought = True
            return [UpbitSignal(symbol="KRW-BTC", target_position=10_000_000.0)]
        return []


def _make_minimal_data(n_bars: int = 60) -> dict:
    base_ms = int(pd.Timestamp("2024-07-01", tz="UTC").timestamp() * 1000)
    rows = [
        {
            "timestamp": base_ms + i * 3_600_000,
            "open": 80_000_000.0, "high": 81_000_000.0,
            "low": 79_000_000.0, "close": 80_000_000.0 + i * 100_000,
            "volume": 1.0,
        }
        for i in range(n_bars)
    ]
    return {"KRW-BTC": pd.DataFrame(rows)}


def test_backtest_do_nothing_returns_zero_trades():
    result = run_upbit_backtest(_DoNothingStrategy(), _make_minimal_data())
    assert result.num_trades == 0
    assert abs(result.total_return_pct) < 0.01


def test_backtest_buy_btc_has_positive_return():
    result = run_upbit_backtest(_AlwaysBuyBTC(), _make_minimal_data(100))
    assert result.num_trades >= 1
    assert result.total_return_pct > 0


def test_short_signal_is_ignored():
    from upbit_prepare import UpbitSignal

    class _ShortStrategy:
        def on_bar(self, bar_data, portfolio):
            return [UpbitSignal(symbol="KRW-BTC", target_position=-5_000_000.0)]

    result = run_upbit_backtest(_ShortStrategy(), _make_minimal_data())
    assert result.num_trades == 0


def test_compute_score_hard_cutoff_no_trades():
    result = UpbitBacktestResult(num_trades=0, max_drawdown_pct=5.0,
                                  equity_curve=[100_000_000.0, 100_000_000.0])
    assert compute_upbit_score(result) == -999.0


def test_full_pipeline_with_synthetic_data(tmp_path, monkeypatch):
    """전체 파이프라인: 데이터 로드 → 전략 → 백테스트 → 스코어."""
    monkeypatch.setattr("upbit_prepare.DATA_DIR", str(tmp_path))

    base_ms = int(pd.Timestamp("2024-07-01", tz="UTC").timestamp() * 1000)
    rows = []
    price = 80_000_000.0
    rng = np.random.default_rng(42)
    for i in range(600):
        price *= 1 + rng.uniform(-0.005, 0.006)
        rows.append({
            "timestamp": base_ms + i * 3_600_000,
            "open": price, "high": price * 1.005,
            "low": price * 0.995, "close": price,
            "volume": rng.uniform(0.5, 2.0),
        })
    df = pd.DataFrame(rows)
    for sym in ["KRW-BTC", "KRW-ETH", "KRW-SOL"]:
        df.to_parquet(tmp_path / f"{sym}_1h.parquet", index=False)

    from upbit_strategy import Strategy
    data = load_upbit_data("val")
    result = run_upbit_backtest(Strategy(), data)
    score  = compute_upbit_score(result)

    assert isinstance(score, float)
    assert score == score   # NaN 체크
    assert result.num_trades >= 0
