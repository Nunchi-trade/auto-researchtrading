import pytest
import pandas as pd
import numpy as np
from upbit_prepare import UpbitPortfolioState, UpbitBarData
from upbit_strategy import Strategy


def _make_history(n: int, base_price: float = 80_000_000.0) -> pd.DataFrame:
    rows = [
        {
            "timestamp": i * 3_600_000,
            "open": base_price, "high": base_price * 1.01,
            "low": base_price * 0.99, "close": base_price + i * 50_000,
            "volume": 1.0,
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


def _make_bar(symbol: str, price: float, n_history: int = 100) -> UpbitBarData:
    hist = _make_history(n_history, price)
    return UpbitBarData(
        symbol=symbol, timestamp=n_history * 3_600_000,
        open=price, high=price * 1.01, low=price * 0.99, close=price,
        volume=1.0, history=hist,
    )


def _make_portfolio(cash: float = 100_000_000.0) -> UpbitPortfolioState:
    return UpbitPortfolioState(cash=cash, positions={}, entry_prices={}, equity=cash)


def test_strategy_returns_list():
    strategy = Strategy()
    bar_data = {"KRW-BTC": _make_bar("KRW-BTC", 80_000_000.0)}
    result = strategy.on_bar(bar_data, _make_portfolio())
    assert isinstance(result, list)


def test_no_short_signals():
    """전략은 절대 음수 target_position을 반환하면 안 된다."""
    strategy = Strategy()
    portfolio = _make_portfolio()
    for i in range(200):
        price = 80_000_000.0 * (1 - 0.001 * i)  # 하락장
        bar_data = {"KRW-BTC": _make_bar("KRW-BTC", price, 150)}
        signals = strategy.on_bar(bar_data, portfolio)
        for sig in signals:
            assert sig.target_position >= 0, f"숏 신호 감지: {sig}"


def test_no_funding_rate_access():
    """history에 funding_rate 컬럼 없어도 에러 없이 실행."""
    strategy = Strategy()
    hist = _make_history(100)
    assert "funding_rate" not in hist.columns
    bar = UpbitBarData(
        symbol="KRW-BTC", timestamp=100 * 3_600_000,
        open=80_000_000.0, high=81_000_000.0,
        low=79_000_000.0, close=80_000_000.0,
        volume=1.0, history=hist,
    )
    result = strategy.on_bar({"KRW-BTC": bar}, _make_portfolio())
    assert isinstance(result, list)


def test_active_symbols_are_upbit_format():
    from upbit_strategy import ACTIVE_SYMBOLS
    for sym in ACTIVE_SYMBOLS:
        assert sym.startswith("KRW-"), f"{sym}은 KRW- 형식이어야 합니다"
