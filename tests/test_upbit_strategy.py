import pytest
import pandas as pd
import numpy as np
import upbit_strategy as strategy_module
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


def test_position_scale_reduces_meaningfully_in_high_volatility():
    """고변동성 구간에서는 포지션 사이즈가 명확하게 줄어야 한다."""
    helper = getattr(strategy_module, "_position_scale_from_volatility", None)
    assert callable(helper), "변동성 기반 포지션 사이징 helper가 필요합니다"

    low_vol_scale = helper(0.0025)
    high_vol_scale = helper(0.0120)

    assert low_vol_scale == pytest.approx(1.0)
    assert high_vol_scale < low_vol_scale
    assert high_vol_scale <= 0.5


def test_strategy_param_override_changes_entry_target(monkeypatch):
    """전략 오버라이드는 실제 진입 target position에 반영돼야 한다."""
    monkeypatch.setattr(strategy_module, "_calc_rsi", lambda closes, period: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_stoch_rsi", lambda closes, rsi_period=8, stoch_period=14: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_macd", lambda closes: 1.0)
    monkeypatch.setattr(strategy_module, "_calc_adx", lambda history_df, period=24: (25.0, 30.0, 10.0))

    hist = _make_history(400)
    price = float(hist["close"].iloc[-1])
    bar = UpbitBarData(
        symbol="KRW-BTC",
        timestamp=400 * 3_600_000,
        open=price,
        high=price * 1.01,
        low=price * 0.99,
        close=price,
        volume=1.0,
        history=hist,
    )
    portfolio = _make_portfolio()

    default_signals = Strategy().on_bar({"KRW-BTC": bar}, portfolio)
    tuned_signals = Strategy({
        "BASE_POSITION_PCT": 0.30,
        "SIZE_TARGET_VOL": 0.0020,
        "MIN_POSITION_SCALE": 0.20,
    }).on_bar({"KRW-BTC": bar}, portfolio)

    assert len(default_signals) == 1
    assert len(tuned_signals) == 1
    assert tuned_signals[0].target_position < default_signals[0].target_position


def test_recent_high_buffer_override_changes_exit_behavior(monkeypatch):
    """recent high buffer를 더 타이트하게 주면 약한 되돌림에서도 청산해야 한다."""
    monkeypatch.setattr(strategy_module, "_calc_rsi", lambda closes, period: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_stoch_rsi", lambda closes, rsi_period=8, stoch_period=14: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_macd", lambda closes: 1.0)
    monkeypatch.setattr(strategy_module, "_calc_adx", lambda history_df, period=24: (25.0, 30.0, 10.0))

    hist = _make_history(400)
    hist.loc[396:, "close"] = [99_200_000.0, 99_600_000.0, 100_000_000.0, 99_700_000.0]
    price = float(hist["close"].iloc[-1])
    bar = UpbitBarData(
        symbol="KRW-BTC",
        timestamp=400 * 3_600_000,
        open=price,
        high=100_000_000.0,
        low=99_500_000.0,
        close=price,
        volume=1.0,
        history=hist,
    )
    portfolio = UpbitPortfolioState(
        cash=90_000_000.0,
        positions={"KRW-BTC": 10_000_000.0},
        entry_prices={"KRW-BTC": 95_000_000.0},
        equity=100_000_000.0,
    )

    loose_exit = Strategy({"MIN_BEAR_VOTES": 1, "RECENT_HIGH_BUFFER": 0.995})
    loose_exit.peak_price["KRW-BTC"] = price
    loose_exit.entry_price["KRW-BTC"] = 95_000_000.0

    tight_exit = Strategy({"MIN_BEAR_VOTES": 1, "RECENT_HIGH_BUFFER": 0.999})
    tight_exit.peak_price["KRW-BTC"] = price
    tight_exit.entry_price["KRW-BTC"] = 95_000_000.0

    assert loose_exit.on_bar({"KRW-BTC": bar}, portfolio) == []

    tight_signals = tight_exit.on_bar({"KRW-BTC": bar}, portfolio)
    assert len(tight_signals) == 1
    assert tight_signals[0].target_position == 0.0


def test_adx_entry_threshold_override_allows_weaker_trend_entry(monkeypatch):
    """ADX entry threshold를 낮추면 약한 추세에서도 진입할 수 있어야 한다."""
    monkeypatch.setattr(strategy_module, "_calc_rsi", lambda closes, period: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_stoch_rsi", lambda closes, rsi_period=8, stoch_period=14: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_macd", lambda closes: 1.0)
    monkeypatch.setattr(strategy_module, "_calc_adx", lambda history_df, period=24: (17.5, 28.0, 12.0))

    hist = _make_history(400)
    price = float(hist["close"].iloc[-1])
    bar = UpbitBarData(
        symbol="KRW-BTC",
        timestamp=400 * 3_600_000,
        open=price,
        high=price * 1.01,
        low=price * 0.99,
        close=price,
        volume=1.0,
        history=hist,
    )
    portfolio = _make_portfolio()

    default_signals = Strategy().on_bar({"KRW-BTC": bar}, portfolio)
    tuned_signals = Strategy({"ADX_ENTRY_THRESHOLD": 16.0}).on_bar({"KRW-BTC": bar}, portfolio)

    assert default_signals == []
    assert len(tuned_signals) == 1


def test_trend_filter_bars_override_allows_shorter_history_entry(monkeypatch):
    """trend filter bars를 줄이면 더 짧은 이력에서도 진입 평가가 가능해야 한다."""
    monkeypatch.setattr(strategy_module, "_calc_rsi", lambda closes, period: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_stoch_rsi", lambda closes, rsi_period=8, stoch_period=14: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_macd", lambda closes: 1.0)
    monkeypatch.setattr(strategy_module, "_calc_adx", lambda history_df, period=24: (25.0, 30.0, 10.0))

    hist = _make_history(320)
    price = float(hist["close"].iloc[-1])
    bar = UpbitBarData(
        symbol="KRW-BTC",
        timestamp=320 * 3_600_000,
        open=price,
        high=price * 1.01,
        low=price * 0.99,
        close=price,
        volume=1.0,
        history=hist,
    )
    portfolio = _make_portfolio()

    default_signals = Strategy().on_bar({"KRW-BTC": bar}, portfolio)
    tuned_signals = Strategy({"TREND_FILTER_BARS": 288}).on_bar({"KRW-BTC": bar}, portfolio)

    assert default_signals == []
    assert len(tuned_signals) == 1


def test_trend_boost_override_increases_entry_target_for_strong_trend(monkeypatch):
    """강한 추세 전용 boost는 동일한 진입에서도 target position을 키워야 한다."""
    monkeypatch.setattr(strategy_module, "_calc_rsi", lambda closes, period: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_stoch_rsi", lambda closes, rsi_period=8, stoch_period=14: 60.0)
    monkeypatch.setattr(strategy_module, "_calc_macd", lambda closes: 1.0)
    monkeypatch.setattr(strategy_module, "_calc_adx", lambda history_df, period=24: (25.0, 30.0, 10.0))

    hist = _make_history(400)
    price = float(hist["close"].iloc[-1])
    bar = UpbitBarData(
        symbol="KRW-BTC",
        timestamp=400 * 3_600_000,
        open=price,
        high=price * 1.01,
        low=price * 0.99,
        close=price,
        volume=1.0,
        history=hist,
    )
    portfolio = _make_portfolio()

    default_signals = Strategy().on_bar({"KRW-BTC": bar}, portfolio)
    boosted_signals = Strategy({
        "TREND_BOOST_MAX": 1.30,
        "ADX_BOOST_THRESHOLD": 20.0,
        "SLOPE_BOOST_THRESHOLD": 0.0030,
    }).on_bar({"KRW-BTC": bar}, portfolio)

    assert len(default_signals) == 1
    assert len(boosted_signals) == 1
    assert boosted_signals[0].target_position > default_signals[0].target_position
