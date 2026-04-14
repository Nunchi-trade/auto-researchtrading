# Upbit 현물 백테스트 시스템 마이그레이션 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hyperliquid 퍼프 선물 백테스트 시스템을 Upbit 현물(KRW) 거래 기반으로 마이그레이션하여 동일한 신호 앙상블로 한국 규제 내 실거래 가능한 전략을 연구한다.

**Architecture:** 기존 `prepare.py` / `backtest.py` 구조를 그대로 복제해 `upbit_prepare.py` / `upbit_backtest.py`를 새로 생성한다. 숏 포지션을 제거하고 KRW 현물 기준으로 엔진을 단순화한다. 전략은 `upbit_strategy.py`에 별도 관리해 기존 `strategy.py`를 보존한다.

**Tech Stack:** Python 3.10+, numpy, pandas, scipy, requests, pyarrow, uv (추가 패키지 없음)

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `upbit_prepare.py` | Upbit 공개 API 데이터 다운로드 + 현물 백테스트 엔진 + 스코어 계산 |
| `upbit_backtest.py` | 진입점 — `upbit_strategy.py`를 임포트해 백테스트 실행 |
| `upbit_strategy.py` | 현물 전용 전략 (숏 제거, 펀딩레이트 제거) |
| `tests/test_upbit_prepare.py` | 데이터 다운로더 + 백테스트 엔진 단위 테스트 |
| `tests/test_upbit_strategy.py` | 전략 단위 테스트 |

> **수정 금지:** `prepare.py`, `backtest.py`, `strategy.py`, `benchmarks/` — 기존 Hyperliquid 시스템 유지

---

## Task 1: Upbit 데이터 타입 및 다운로더

**Files:**
- Create: `upbit_prepare.py` (데이터 타입 + 다운로더 함수)
- Create: `tests/test_upbit_prepare.py`

Upbit 공개 API 스펙:
- `GET https://api.upbit.com/v1/candles/minutes/60`
- 파라미터: `market` (예: `KRW-BTC`), `count` (최대 200), `to` (ISO 8601, UTC)
- 응답 필드: `candle_date_time_utc`, `opening_price`, `high_price`, `low_price`, `trade_price`(종가), `candle_acc_trade_volume`
- Rate limit: 10 req/sec (공개 API)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
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
        mock_resp.json.side_effect = [fake_candles, []]  # second call → stop
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
    import inspect
    import dataclasses
    fields = {f.name for f in dataclasses.fields(UpbitBarData)}
    assert "funding_rate" not in fields
    assert "history" in fields
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
cd /home/bigtrader91/workspace/auto-researchtrading
uv run pytest tests/test_upbit_prepare.py -v 2>&1 | head -30
```

예상 결과: `ModuleNotFoundError: No module named 'upbit_prepare'`

- [ ] **Step 3: 데이터 타입 및 다운로더 구현**

```python
# upbit_prepare.py
"""
Upbit 현물 백테스트 시스템. prepare.py의 Upbit 버전.
Usage:
    uv run upbit_prepare.py                    # 데이터 다운로드
    uv run upbit_prepare.py --symbols KRW-BTC  # 특정 심볼만
"""

import os
import sys
import time
import math
import signal as _signal
import argparse
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

TIME_BUDGET = 120
INITIAL_CAPITAL = 100_000_000.0   # 1억 KRW
TAKER_FEE = 0.0005                # 0.05% (Upbit 기본)
SLIPPAGE_BPS = 1.0
LOOKBACK_BARS = 500
HOURS_PER_YEAR = 8760

SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-SOL"]

VAL_START = "2024-07-01"
VAL_END   = "2025-03-31"

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "autotrader_upbit")
DATA_DIR  = os.path.join(CACHE_DIR, "data")

UPBIT_URL = "https://api.upbit.com/v1"

# ---------------------------------------------------------------------------
# 데이터 타입
# ---------------------------------------------------------------------------

@dataclass
class UpbitBarData:
    symbol: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    history: pd.DataFrame   # 최근 LOOKBACK_BARS 봉 (funding_rate 없음)

@dataclass
class UpbitSignal:
    symbol: str
    target_position: float  # KRW 명목 (>= 0, 현물이므로 숏 없음)
    order_type: str = "market"

@dataclass
class UpbitPortfolioState:
    cash: float             # 보유 KRW
    positions: dict         # symbol -> KRW 명목
    entry_prices: dict      # symbol -> 평균 매수가
    equity: float = 0.0
    timestamp: int = 0

@dataclass
class UpbitBacktestResult:
    sharpe: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    num_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    annual_turnover: float = 0.0
    backtest_seconds: float = 0.0
    equity_curve: list = field(default_factory=list)
    trade_log: list = field(default_factory=list)

# ---------------------------------------------------------------------------
# 데이터 다운로드
# ---------------------------------------------------------------------------

def _download_upbit_candles(market: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Upbit 공개 API로 시간봉 OHLCV 다운로드."""
    all_rows = []
    current_end_ms = end_ms

    while current_end_ms > start_ms:
        to_str = datetime.utcfromtimestamp(current_end_ms / 1000).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = requests.get(
            f"{UPBIT_URL}/candles/minutes/60",
            params={"market": market, "count": 200, "to": to_str},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data:
            break

        for bar in data:
            ts_ms = int(pd.Timestamp(bar["candle_date_time_utc"] + "+00:00").timestamp() * 1000)
            if ts_ms < start_ms:
                continue
            all_rows.append({
                "timestamp": ts_ms,
                "open":   float(bar["opening_price"]),
                "high":   float(bar["high_price"]),
                "low":    float(bar["low_price"]),
                "close":  float(bar["trade_price"]),
                "volume": float(bar["candle_acc_trade_volume"]),
            })

        earliest_ms = int(pd.Timestamp(data[-1]["candle_date_time_utc"] + "+00:00").timestamp() * 1000)
        if earliest_ms >= current_end_ms:
            break
        current_end_ms = earliest_ms - 1
        time.sleep(0.12)

    if not all_rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(all_rows)
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
        .reset_index(drop=True)
    )
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/test_upbit_prepare.py::test_download_returns_dataframe_with_required_columns \
              tests/test_upbit_prepare.py::test_symbols_list \
              tests/test_upbit_prepare.py::test_upbit_bar_data_has_no_funding_rate -v
```

예상 결과: `3 passed`

- [ ] **Step 5: 커밋**

```bash
git add upbit_prepare.py tests/test_upbit_prepare.py
git commit -m "feat: add Upbit data types and candle downloader"
```

---

## Task 2: `download_upbit_data` 및 `load_upbit_data` 구현

**Files:**
- Modify: `upbit_prepare.py` (Task 1에서 생성)
- Modify: `tests/test_upbit_prepare.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_upbit_prepare.py` 끝에 추가:

```python
import os
import tempfile


def test_load_upbit_data_returns_symbols(tmp_path, monkeypatch):
    """로컬 parquet 파일이 있으면 val split을 올바르게 로드한다."""
    monkeypatch.setattr("upbit_prepare.DATA_DIR", str(tmp_path))

    # 테스트용 parquet 생성
    rows = []
    base_ms = int(pd.Timestamp("2024-07-01", tz="UTC").timestamp() * 1000)
    for i in range(10):
        rows.append({
            "timestamp": base_ms + i * 3600_000,
            "open": 80000000.0, "high": 81000000.0,
            "low": 79000000.0, "close": 80500000.0,
            "volume": 1.0,
        })
    df = pd.DataFrame(rows)
    df.to_parquet(tmp_path / "KRW-BTC_1h.parquet", index=False)

    data = load_upbit_data("val")
    assert "KRW-BTC" in data
    assert len(data["KRW-BTC"]) == 10


def test_load_upbit_data_skips_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr("upbit_prepare.DATA_DIR", str(tmp_path))
    data = load_upbit_data("val")
    assert data == {}
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/test_upbit_prepare.py::test_load_upbit_data_returns_symbols -v
```

예상: `AttributeError: module 'upbit_prepare' has no attribute 'load_upbit_data'`

- [ ] **Step 3: `download_upbit_data` / `load_upbit_data` 구현**

`upbit_prepare.py`의 다운로드 함수 아래에 추가:

```python
def download_upbit_data(symbols=None):
    """모든 심볼의 시간봉 데이터 다운로드 (캐시 있으면 스킵)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if symbols is None:
        symbols = SYMBOLS

    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp("2025-04-01", tz="UTC").timestamp() * 1000)

    for symbol in symbols:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1h.parquet")
        if os.path.exists(filepath):
            existing = pd.read_parquet(filepath)
            print(f"  {symbol}: 이미 {len(existing)} 봉 보유")
            continue

        print(f"  {symbol}: Upbit API 다운로드 중...")
        df = _download_upbit_candles(symbol, start_ms, end_ms)

        if df.empty:
            print(f"  {symbol}: 데이터 없음, 스킵")
            continue

        df.to_parquet(filepath, index=False)
        print(f"  {symbol}: {len(df)} 봉 저장 → {filepath}")


def load_upbit_data(split: str = "val") -> dict:
    """parquet 캐시에서 split 데이터 로드. {symbol: DataFrame} 반환."""
    splits = {"val": (VAL_START, VAL_END)}
    assert split in splits, f"split은 {list(splits.keys())} 중 하나여야 합니다"

    start_str, end_str = splits[split]
    start_ms = int(pd.Timestamp(start_str, tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp(end_str,   tz="UTC").timestamp() * 1000)

    result = {}
    for symbol in SYMBOLS:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1h.parquet")
        if not os.path.exists(filepath):
            continue
        df = pd.read_parquet(filepath)
        mask = (df["timestamp"] >= start_ms) & (df["timestamp"] < end_ms)
        split_df = df[mask].reset_index(drop=True)
        if len(split_df) > 0:
            result[symbol] = split_df
    return result
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_upbit_prepare.py -v
```

예상: `5 passed`

- [ ] **Step 5: 커밋**

```bash
git add upbit_prepare.py tests/test_upbit_prepare.py
git commit -m "feat: add download_upbit_data and load_upbit_data"
```

---

## Task 3: 현물 백테스트 엔진 (`run_upbit_backtest` + `compute_upbit_score`)

**Files:**
- Modify: `upbit_prepare.py`
- Modify: `tests/test_upbit_prepare.py`

핵심 차이점 vs Hyperliquid 엔진:
1. `funding_rate` 없음 → 포트폴리오 현금 조정 없음
2. `target_position >= 0` 강제 (현물 숏 불가)
3. 포지션 오픈 시 현금 차감, 클로즈 시 현금 회수

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_upbit_prepare.py 끝에 추가
from upbit_prepare import run_upbit_backtest, compute_upbit_score, UpbitBacktestResult


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
    """target_position < 0 이면 무시해야 한다."""
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/test_upbit_prepare.py::test_backtest_do_nothing_returns_zero_trades -v
```

예상: `ImportError: cannot import name 'run_upbit_backtest'`

- [ ] **Step 3: 백테스트 엔진 구현**

`upbit_prepare.py` 하단에 추가 (load_upbit_data 아래):

```python
# ---------------------------------------------------------------------------
# 백테스트 엔진
# ---------------------------------------------------------------------------

def run_upbit_backtest(strategy, data: dict) -> UpbitBacktestResult:
    """현물 전략을 data 위에서 실행. UpbitBacktestResult 반환."""
    import time as _time
    t_start = _time.time()

    all_timestamps = set()
    for df in data.values():
        all_timestamps.update(df["timestamp"].tolist())
    timestamps = sorted(all_timestamps)

    if not timestamps:
        return UpbitBacktestResult()

    indexed = {symbol: df.set_index("timestamp") for symbol, df in data.items()}

    portfolio = UpbitPortfolioState(
        cash=INITIAL_CAPITAL,
        positions={},
        entry_prices={},
        equity=INITIAL_CAPITAL,
        timestamp=0,
    )

    equity_curve = [INITIAL_CAPITAL]
    hourly_returns = []
    trade_log = []
    total_volume = 0.0
    prev_equity = INITIAL_CAPITAL
    history_buffers = {symbol: [] for symbol in data}

    for ts in timestamps:
        if _time.time() - t_start > TIME_BUDGET:
            break

        portfolio.timestamp = ts

        # 봉 데이터 구성
        bar_data = {}
        for symbol in data:
            if ts not in indexed[symbol].index:
                continue
            row = indexed[symbol].loc[ts]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]

            bar_dict = {
                "timestamp": ts,
                "open": row["open"], "high": row["high"],
                "low": row["low"],   "close": row["close"],
                "volume": row["volume"],
            }
            history_buffers[symbol].append(bar_dict)
            if len(history_buffers[symbol]) > LOOKBACK_BARS:
                history_buffers[symbol] = history_buffers[symbol][-LOOKBACK_BARS:]

            bar_data[symbol] = UpbitBarData(
                symbol=symbol, timestamp=ts,
                open=row["open"], high=row["high"],
                low=row["low"],   close=row["close"],
                volume=row["volume"],
                history=pd.DataFrame(history_buffers[symbol]),
            )

        if not bar_data:
            continue

        # 시가총액 평가 (mark-to-market)
        unrealized = 0.0
        for sym, pos in portfolio.positions.items():
            if sym in bar_data:
                entry = portfolio.entry_prices.get(sym, bar_data[sym].close)
                if entry > 0:
                    unrealized += pos * (bar_data[sym].close - entry) / entry

        portfolio.equity = portfolio.cash + sum(abs(v) for v in portfolio.positions.values()) + unrealized

        # 전략 신호 수신
        try:
            signals = strategy.on_bar(bar_data, portfolio) or []
        except Exception:
            signals = []

        # 신호 실행
        for sig in signals:
            if sig.symbol not in bar_data:
                continue
            # 현물: 숏 불가
            if sig.target_position < 0:
                continue

            current_price = bar_data[sig.symbol].close
            current_pos = portfolio.positions.get(sig.symbol, 0.0)
            delta = sig.target_position - current_pos

            if abs(delta) < 1.0:
                continue

            slippage = current_price * SLIPPAGE_BPS / 10000
            exec_price = current_price + slippage if delta > 0 else current_price - slippage
            fee = abs(delta) * TAKER_FEE
            portfolio.cash -= fee
            total_volume += abs(delta)

            if sig.target_position == 0:
                # 포지션 청산 → 수익 실현
                entry = portfolio.entry_prices.get(sig.symbol, exec_price)
                pnl = current_pos * (exec_price - entry) / entry if entry > 0 else 0.0
                portfolio.cash += abs(current_pos) + pnl
                portfolio.positions.pop(sig.symbol, None)
                portfolio.entry_prices.pop(sig.symbol, None)
                trade_log.append(("close", sig.symbol, delta, exec_price, pnl))

            elif current_pos == 0:
                # 신규 매수
                portfolio.cash -= abs(sig.target_position)
                portfolio.positions[sig.symbol] = sig.target_position
                portfolio.entry_prices[sig.symbol] = exec_price
                trade_log.append(("open", sig.symbol, delta, exec_price, 0))

            else:
                # 포지션 조정
                old_entry = portfolio.entry_prices.get(sig.symbol, exec_price)
                if abs(sig.target_position) < abs(current_pos):
                    reduced = abs(current_pos) - abs(sig.target_position)
                    pnl = reduced * (exec_price - old_entry) / old_entry if old_entry > 0 else 0.0
                    portfolio.cash += reduced + pnl
                else:
                    added = abs(sig.target_position) - abs(current_pos)
                    portfolio.cash -= added
                    total_notional = abs(current_pos) + added
                    if total_notional > 0:
                        portfolio.entry_prices[sig.symbol] = (
                            old_entry * abs(current_pos) + exec_price * added
                        ) / total_notional
                portfolio.positions[sig.symbol] = sig.target_position
                trade_log.append(("modify", sig.symbol, delta, exec_price, 0))

        # 시가총액 재계산
        unrealized = 0.0
        for sym, pos in portfolio.positions.items():
            if sym in bar_data:
                entry = portfolio.entry_prices.get(sym, bar_data[sym].close)
                if entry > 0:
                    unrealized += pos * (bar_data[sym].close - entry) / entry

        current_equity = portfolio.cash + sum(abs(v) for v in portfolio.positions.values()) + unrealized
        equity_curve.append(current_equity)

        if prev_equity > 0:
            hourly_returns.append((current_equity - prev_equity) / prev_equity)
        prev_equity = current_equity

        if current_equity < INITIAL_CAPITAL * 0.01:
            break

    t_end = _time.time()

    returns = np.array(hourly_returns) if hourly_returns else np.array([0.0])
    eq = np.array(equity_curve)

    sharpe = (returns.mean() / returns.std()) * np.sqrt(HOURS_PER_YEAR) if returns.std() > 0 else 0.0
    final_equity = eq[-1] if len(eq) > 0 else INITIAL_CAPITAL
    total_return_pct = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    peak = np.maximum.accumulate(eq)
    drawdown = (peak - eq) / np.where(peak > 0, peak, 1)
    max_drawdown_pct = drawdown.max() * 100

    trade_pnls = [t[4] for t in trade_log if t[0] == "close"]
    num_trades = len(trade_log)
    if trade_pnls:
        wins   = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        win_rate_pct = len(wins) / len(trade_pnls) * 100
        profit_factor = sum(wins) / max(abs(sum(losses)), 1e-10)
    else:
        win_rate_pct = profit_factor = 0.0

    data_hours = len(timestamps)
    annual_turnover = total_volume * (HOURS_PER_YEAR / data_hours) if data_hours > 0 else 0.0

    return UpbitBacktestResult(
        sharpe=sharpe,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        num_trades=num_trades,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        annual_turnover=annual_turnover,
        backtest_seconds=t_end - t_start,
        equity_curve=equity_curve,
        trade_log=trade_log,
    )


def compute_upbit_score(result: UpbitBacktestResult) -> float:
    """Hyperliquid와 동일한 스코어 공식 (비교 가능하도록)."""
    if result.num_trades < 10:
        return -999.0
    if result.max_drawdown_pct > 50.0:
        return -999.0
    final_equity = result.equity_curve[-1] if result.equity_curve else INITIAL_CAPITAL
    if final_equity < INITIAL_CAPITAL * 0.5:
        return -999.0

    trade_count_factor = min(result.num_trades / 50.0, 1.0)
    drawdown_penalty = max(0, result.max_drawdown_pct - 15.0) * 0.05
    turnover_ratio = result.annual_turnover / INITIAL_CAPITAL
    turnover_penalty = max(0, turnover_ratio - 500) * 0.001

    return result.sharpe * math.sqrt(trade_count_factor) - drawdown_penalty - turnover_penalty
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_upbit_prepare.py -v
```

예상: `9 passed`

- [ ] **Step 5: 커밋**

```bash
git add upbit_prepare.py tests/test_upbit_prepare.py
git commit -m "feat: add Upbit spot backtest engine and score computation"
```

---

## Task 4: 현물 전용 전략 (`upbit_strategy.py`)

**Files:**
- Create: `upbit_strategy.py`
- Create: `tests/test_upbit_strategy.py`

현재 `strategy.py`(exp102)에서 변경할 부분:
1. `ACTIVE_SYMBOLS` → `["KRW-BTC", "KRW-ETH", "KRW-SOL"]`
2. `FUNDING_BOOST`, `avg_funding`, `funding_mult` 로직 제거 → 항상 `funding_mult = 1.0`
3. `bearish` 신호 → `target = 0.0` (캐시 보유, 숏 없음)
4. 역방향 전환 로직 제거 (`current_pos < 0 and bullish` → 해당 없음)
5. `bar_data[symbol].history`에 `funding_rate` 컬럼이 없으므로 참조 제거

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_upbit_strategy.py
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
    """전략은 절대 음수 target_position을 반환해서는 안 된다."""
    strategy = Strategy()
    # 충분한 히스토리로 여러 봉 실행
    portfolio = _make_portfolio()
    for i in range(200):
        price = 80_000_000.0 * (1 - 0.001 * i)  # 하락장 (숏 신호 유도)
        bar_data = {"KRW-BTC": _make_bar("KRW-BTC", price, 150)}
        signals = strategy.on_bar(bar_data, portfolio)
        for sig in signals:
            assert sig.target_position >= 0, f"숏 신호 감지: {sig}"


def test_no_funding_rate_access():
    """history DataFrame에 funding_rate 컬럼이 없어도 에러 없이 실행된다."""
    strategy = Strategy()
    hist = _make_history(100)
    assert "funding_rate" not in hist.columns
    bar = UpbitBarData(
        symbol="KRW-BTC", timestamp=100 * 3_600_000,
        open=80_000_000.0, high=81_000_000.0,
        low=79_000_000.0, close=80_000_000.0,
        volume=1.0, history=hist,
    )
    # 에러 없이 실행되어야 함
    result = strategy.on_bar({"KRW-BTC": bar}, _make_portfolio())
    assert isinstance(result, list)


def test_active_symbols_are_upbit_format():
    from upbit_strategy import ACTIVE_SYMBOLS
    for sym in ACTIVE_SYMBOLS:
        assert sym.startswith("KRW-"), f"{sym}은 KRW- 형식이어야 합니다"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

```bash
uv run pytest tests/test_upbit_strategy.py -v 2>&1 | head -20
```

예상: `ModuleNotFoundError: No module named 'upbit_strategy'`

- [ ] **Step 3: 현물 전략 구현**

```python
# upbit_strategy.py
"""
Upbit 현물 전용 전략. strategy.py(exp102) 기반, 숏/펀딩레이트 제거.

변경사항:
- ACTIVE_SYMBOLS: KRW-BTC, KRW-ETH, KRW-SOL
- 베어리시 신호 → target = 0.0 (캐시 보유, 숏 없음)
- funding_rate 참조 완전 제거
- 역방향 전환 로직 제거
"""

import numpy as np
from upbit_prepare import UpbitSignal, UpbitPortfolioState, UpbitBarData

ACTIVE_SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
SYMBOL_WEIGHTS = {"KRW-BTC": 0.33, "KRW-ETH": 0.33, "KRW-SOL": 0.33}

SHORT_WINDOW = 6
MED_WINDOW   = 12
EMA_FAST     = 7
EMA_SLOW     = 26
RSI_PERIOD   = 8
RSI_BULL     = 50
RSI_BEAR     = 50
RSI_OVERBOUGHT = 69
RSI_OVERSOLD   = 31

MACD_FAST   = 14
MACD_SLOW   = 23
MACD_SIGNAL = 9

BB_PERIOD   = 7

BASE_POSITION_PCT = 0.08
VOL_LOOKBACK      = 36
TARGET_VOL        = 0.015
ATR_LOOKBACK      = 24
ATR_STOP_MULT     = 5.5
TAKE_PROFIT_PCT   = 99.0
BASE_THRESHOLD    = 0.012

COOLDOWN_BARS = 2
MIN_VOTES     = 4   # 6개 신호 중 4개


def _ema(values, span):
    alpha = 2.0 / (span + 1)
    result = np.empty_like(values, dtype=float)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


def _calc_rsi(closes, period):
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains  = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    rs = np.mean(gains) / max(np.mean(losses), 1e-10)
    return 100 - 100 / (1 + rs)


def _calc_atr(history, lookback):
    if len(history) < lookback + 1:
        return None
    highs  = history["high"].values[-lookback:]
    lows   = history["low"].values[-lookback:]
    closes = history["close"].values[-(lookback + 1):-1]
    tr = np.maximum(highs - lows,
                    np.maximum(np.abs(highs - closes), np.abs(lows - closes)))
    return np.mean(tr)


def _calc_macd(closes):
    if len(closes) < MACD_SLOW + MACD_SIGNAL + 5:
        return 0.0
    buf = closes[-(MACD_SLOW + MACD_SIGNAL + 5):]
    macd_line   = _ema(buf, MACD_FAST) - _ema(buf, MACD_SLOW)
    signal_line = _ema(macd_line, MACD_SIGNAL)
    return macd_line[-1] - signal_line[-1]


def _calc_bb_width_pctile(closes, period):
    if len(closes) < period * 3:
        return 50.0
    widths = []
    for i in range(period * 2, len(closes)):
        w = closes[i - period:i]
        sma = np.mean(w)
        width = (2 * np.std(w)) / sma if sma > 0 else 0
        widths.append(width)
    if len(widths) < 2:
        return 50.0
    return 100 * np.sum(np.array(widths) <= widths[-1]) / len(widths)


class Strategy:
    def __init__(self):
        self.entry_prices  = {}
        self.peak_prices   = {}
        self.atr_at_entry  = {}
        self.peak_equity   = INITIAL_CAPITAL = 100_000_000.0
        self.exit_bar      = {}
        self.bar_count     = 0

    def on_bar(self, bar_data: dict, portfolio: UpbitPortfolioState) -> list:
        signals = []
        equity = portfolio.equity if portfolio.equity > 0 else portfolio.cash
        self.bar_count += 1
        self.peak_equity = max(self.peak_equity, equity)

        min_history = max(EMA_SLOW, MACD_SLOW + MACD_SIGNAL + 5, BB_PERIOD * 3) + 1

        for symbol in ACTIVE_SYMBOLS:
            if symbol not in bar_data:
                continue
            bd = bar_data[symbol]
            if len(bd.history) < min_history:
                continue

            closes = bd.history["close"].values
            mid    = bd.close

            # 변동성 기반 동적 임계값
            if len(closes) >= VOL_LOOKBACK:
                log_rets     = np.diff(np.log(closes[-VOL_LOOKBACK:]))
                realized_vol = max(np.std(log_rets), 1e-6)
            else:
                realized_vol = TARGET_VOL
            vol_ratio      = realized_vol / TARGET_VOL
            dyn_threshold  = np.clip(BASE_THRESHOLD * (0.3 + vol_ratio * 0.7), 0.005, 0.020)

            # 6개 신호 계산
            ret_short  = (closes[-1] - closes[-MED_WINDOW])   / closes[-MED_WINDOW]
            ret_vshort = (closes[-1] - closes[-SHORT_WINDOW])  / closes[-SHORT_WINDOW]

            ema_f = _ema(closes[-(EMA_SLOW + 10):], EMA_FAST)
            ema_s = _ema(closes[-(EMA_SLOW + 10):], EMA_SLOW)

            rsi          = _calc_rsi(closes, RSI_PERIOD)
            macd_hist    = _calc_macd(closes)
            bb_pctile    = _calc_bb_width_pctile(closes, BB_PERIOD)
            bb_compressed = bb_pctile < 90

            mom_bull    = ret_short  >  dyn_threshold
            vshort_bull = ret_vshort >  dyn_threshold * 0.7
            ema_bull    = ema_f[-1]  >  ema_s[-1]
            rsi_bull    = rsi > RSI_BULL
            macd_bull   = macd_hist > 0

            # 베어 신호는 캐시 보유 결정에만 사용
            mom_bear    = ret_short  < -dyn_threshold
            vshort_bear = ret_vshort < -dyn_threshold * 0.7
            ema_bear    = ema_f[-1]  <  ema_s[-1]
            rsi_bear    = rsi < RSI_BEAR
            macd_bear   = macd_hist < 0

            bull_votes = sum([mom_bull, vshort_bull, ema_bull, rsi_bull, macd_bull, bb_compressed])
            bear_votes = sum([mom_bear, vshort_bear, ema_bear, rsi_bear, macd_bear, bb_compressed])

            bullish = bull_votes >= MIN_VOTES
            bearish = bear_votes >= MIN_VOTES

            in_cooldown = (self.bar_count - self.exit_bar.get(symbol, -999)) < COOLDOWN_BARS

            weight = SYMBOL_WEIGHTS.get(symbol, 0.33)
            size   = equity * BASE_POSITION_PCT * weight

            current_pos = portfolio.positions.get(symbol, 0.0)
            target = current_pos

            if current_pos == 0:
                if bullish and not in_cooldown:
                    target = size

            else:
                # ATR 트레일링 스탑
                atr = _calc_atr(bd.history, ATR_LOOKBACK) or self.atr_at_entry.get(symbol, mid * 0.02)

                if symbol not in self.peak_prices:
                    self.peak_prices[symbol] = mid
                self.peak_prices[symbol] = max(self.peak_prices[symbol], mid)

                stop = self.peak_prices[symbol] - ATR_STOP_MULT * atr
                if mid < stop:
                    target = 0.0

                # RSI 과매수 청산
                if rsi > RSI_OVERBOUGHT:
                    target = 0.0

                # 베어 신호 → 청산 (현물이므로 숏 진입 없음)
                if bearish and not in_cooldown:
                    target = 0.0

            if abs(target - current_pos) > 1.0:
                signals.append(UpbitSignal(symbol=symbol, target_position=target))
                if target > 0 and current_pos == 0:
                    self.entry_prices[symbol]  = mid
                    self.peak_prices[symbol]   = mid
                    self.atr_at_entry[symbol]  = _calc_atr(bd.history, ATR_LOOKBACK) or mid * 0.02
                elif target == 0:
                    self.entry_prices.pop(symbol, None)
                    self.peak_prices.pop(symbol, None)
                    self.atr_at_entry.pop(symbol, None)
                    self.exit_bar[symbol] = self.bar_count

        return signals
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_upbit_strategy.py -v
```

예상: `4 passed`

- [ ] **Step 5: 커밋**

```bash
git add upbit_strategy.py tests/test_upbit_strategy.py
git commit -m "feat: add Upbit spot-only strategy (no shorts, no funding rate)"
```

---

## Task 5: 진입점 (`upbit_backtest.py`, `upbit_prepare_run.py`) 및 통합 테스트

**Files:**
- Create: `upbit_backtest.py`
- Create: `upbit_prepare_run.py`
- Modify: `tests/test_upbit_prepare.py`

- [ ] **Step 1: 실패하는 통합 테스트 작성**

```python
# tests/test_upbit_prepare.py 끝에 추가
def test_full_pipeline_with_synthetic_data(tmp_path, monkeypatch):
    """전체 파이프라인: 데이터 로드 → 전략 → 백테스트 → 스코어."""
    monkeypatch.setattr("upbit_prepare.DATA_DIR", str(tmp_path))

    # 충분한 합성 데이터 생성 (500봉 이상)
    base_ms = int(pd.Timestamp("2024-07-01", tz="UTC").timestamp() * 1000)
    rows = []
    price = 80_000_000.0
    for i in range(600):
        price *= 1 + np.random.uniform(-0.005, 0.006)
        rows.append({
            "timestamp": base_ms + i * 3_600_000,
            "open": price, "high": price * 1.005,
            "low": price * 0.995, "close": price,
            "volume": np.random.uniform(0.5, 2.0),
        })
    df = pd.DataFrame(rows)
    for sym in ["KRW-BTC", "KRW-ETH", "KRW-SOL"]:
        df.to_parquet(tmp_path / f"{sym}_1h.parquet", index=False)

    from upbit_strategy import Strategy
    data = load_upbit_data("val")
    result = run_upbit_backtest(Strategy(), data)
    score  = compute_upbit_score(result)

    # 스코어가 유효한 숫자여야 함
    assert isinstance(score, float)
    assert score == score  # NaN 체크
```

- [ ] **Step 2: 테스트 실행 → 통과 확인**

```bash
uv run pytest tests/test_upbit_prepare.py::test_full_pipeline_with_synthetic_data -v
```

예상: `1 passed`

- [ ] **Step 3: 진입점 파일 생성**

```python
# upbit_prepare_run.py
"""데이터 다운로드 진입점. Usage: uv run upbit_prepare_run.py"""
import argparse
from upbit_prepare import download_upbit_data, DATA_DIR

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=None)
    args = parser.parse_args()

    print(f"캐시 디렉토리: {DATA_DIR}")
    print("Upbit 데이터 다운로드 중...")
    download_upbit_data(args.symbols)
    print("완료! 백테스트 준비됨.")
```

```python
# upbit_backtest.py
"""
Upbit 현물 백테스트 진입점.
Usage: uv run upbit_backtest.py
"""
import time
from upbit_prepare import load_upbit_data, run_upbit_backtest, compute_upbit_score

t_start = time.time()

from upbit_strategy import Strategy

strategy = Strategy()
data = load_upbit_data("val")

if not data:
    print("데이터 없음. 먼저 실행하세요: uv run upbit_prepare_run.py")
    exit(1)

print(f"로드: {sum(len(df) for df in data.values())} 봉 / {len(data)} 심볼")
print(f"심볼: {list(data.keys())}")

result = run_upbit_backtest(strategy, data)
score  = compute_upbit_score(result)

print("---")
print(f"score:              {score:.6f}")
print(f"sharpe:             {result.sharpe:.6f}")
print(f"total_return_pct:   {result.total_return_pct:.6f}")
print(f"max_drawdown_pct:   {result.max_drawdown_pct:.6f}")
print(f"num_trades:         {result.num_trades}")
print(f"win_rate_pct:       {result.win_rate_pct:.6f}")
print(f"profit_factor:      {result.profit_factor:.6f}")
print(f"annual_turnover:    {result.annual_turnover:.2f}")
print(f"total_seconds:      {time.time() - t_start:.1f}")
```

- [ ] **Step 4: 전체 테스트 통과 확인**

```bash
uv run pytest tests/ -v
```

예상: `모든 테스트 passed`

- [ ] **Step 5: 최종 커밋**

```bash
git add upbit_backtest.py upbit_prepare_run.py
git commit -m "feat: add upbit_backtest.py and upbit_prepare_run.py entry points"
```

---

## 사용법 요약

```bash
uv run upbit_prepare_run.py       # 데이터 다운로드 (~2분)
uv run upbit_backtest.py          # 현물 전략 백테스트
```

---

## 다음 단계 (Phase 2 — 별도 플랜)

현물 백테스트가 검증되면:
- **Upbit Open API 실거래 연동** — Access Key/Secret Key, JWT 인증, 주문 API
- 리스크 관리 (일일 손실 한도, 최대 포지션 크기)
- 실시간 시가 데이터 수신 (WebSocket)
