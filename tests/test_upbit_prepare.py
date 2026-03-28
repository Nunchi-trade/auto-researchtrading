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
    assert "KRW-ETH" in SYMBOLS
    assert "KRW-SOL" in SYMBOLS


def test_upbit_bar_data_has_no_funding_rate():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(UpbitBarData)}
    assert "funding_rate" not in fields
    assert "history" in fields
