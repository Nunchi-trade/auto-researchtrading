"""
Upbit 현물 백테스트 시스템. prepare.py의 Upbit 버전.
Usage:
    uv run upbit_prepare.py                    # 데이터 다운로드
    uv run upbit_prepare.py --symbols KRW-BTC  # 특정 심볼만
"""

import os
import time
import math
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

TIME_BUDGET = 120
INITIAL_CAPITAL = 100_000_000.0   # 1억 KRW
TAKER_FEE = 0.0005                # 0.05%
SLIPPAGE_BPS = 1.0
LOOKBACK_BARS = 500
HOURS_PER_YEAR = 8760

SYMBOLS = ["KRW-BTC"]

DOWNLOAD_START        = "2017-09-01"   # Upbit KRW-BTC 상장 초기
DOWNLOAD_INTERVAL_MIN = 1              # 저장 단위: 1분봉

TRAIN_START = "2017-09-01"
TRAIN_END   = "2022-12-31"

VAL_START   = "2023-01-01"
VAL_END     = "2024-06-30"

TEST_START  = "2024-07-01"
TEST_END    = "2026-03-29"

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
    cash: float
    positions: dict
    entry_prices: dict
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

def _download_upbit_candles(
    market: str, start_ms: int, end_ms: int, interval_minutes: int = 1
) -> pd.DataFrame:
    """Upbit 공개 API로 OHLCV 다운로드.

    Args:
        interval_minutes: 봉 단위 (1, 3, 5, 10, 15, 30, 60, 240)
    """
    all_rows = []
    current_end_ms = end_ms
    req_count = 0

    while current_end_ms > start_ms:
        to_str = datetime.fromtimestamp(
            current_end_ms / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = requests.get(
            f"{UPBIT_URL}/candles/minutes/{interval_minutes}",
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

        req_count += 1
        if req_count % 500 == 0:
            fetched_ts = pd.Timestamp(earliest_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d")
            print(f"    {req_count:,}회 요청 완료 (현재 위치: {fetched_ts}, 누적 {len(all_rows):,} 봉)")

        time.sleep(0.12)

    if not all_rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(all_rows)
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
        .reset_index(drop=True)
    )


def resample_candles(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """1분봉 DataFrame을 지정 분봉으로 리샘플링.

    Args:
        df: 1분봉 OHLCV DataFrame (timestamp 컬럼 ms 단위)
        minutes: 목표 봉 단위 (1, 5, 10, 15, 30, 60, 240, ...)

    Returns:
        리샘플링된 OHLCV DataFrame
    """
    if minutes == 1:
        return df.copy()

    idx = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df2 = df.set_index(idx)

    agg = df2.resample(f"{minutes}min").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["close"])

    agg["timestamp"] = (agg.index.view("int64") // 1_000_000).astype(int)
    return agg.reset_index(drop=True)[["timestamp", "open", "high", "low", "close", "volume"]]


def download_upbit_data(symbols: list[str] | None = None) -> None:
    """1분봉 데이터를 DOWNLOAD_START부터 현재까지 다운로드 (캐시 있으면 스킵).

    저장 경로: DATA_DIR/{symbol}_1m.parquet
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    if symbols is None:
        symbols = SYMBOLS

    start_ms = int(pd.Timestamp(DOWNLOAD_START, tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp("now", tz="UTC").timestamp() * 1000)
    # 캐시 유효 여부 판단 기준: 마지막 봉이 1시간 이내면 최신 상태
    fresh_threshold_ms = end_ms - 3_600_000

    for symbol in symbols:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1m.parquet")
        if os.path.exists(filepath):
            try:
                existing = pd.read_parquet(filepath)
                cached_start = int(existing["timestamp"].min())
                cached_end   = int(existing["timestamp"].max())
                if cached_start <= start_ms and cached_end >= fresh_threshold_ms:
                    print(f"  {symbol}: 이미 {len(existing):,} 봉 보유 (최신)")
                    continue
                print(f"  {symbol}: 캐시 범위 부족, 재다운로드합니다")
            except Exception:
                print(f"  {symbol}: 캐시 파일 손상, 재다운로드합니다")

        print(f"  {symbol}: 1분봉 다운로드 중 ({DOWNLOAD_START} ~ 현재, 약 40분 소요)...")
        try:
            df = _download_upbit_candles(symbol, start_ms, end_ms, DOWNLOAD_INTERVAL_MIN)
        except requests.RequestException as e:
            print(f"  {symbol}: 네트워크 오류 ({e}), 스킵")
            continue

        if df.empty:
            print(f"  {symbol}: 데이터 없음, 스킵")
            continue

        df.to_parquet(filepath, index=False)
        print(f"  {symbol}: {len(df):,} 봉 저장 → {filepath}")


def load_upbit_data(
    split: str = "val", interval_minutes: int = 60
) -> dict[str, pd.DataFrame]:
    """1분봉 parquet에서 로드 후 interval_minutes 봉으로 리샘플링.

    Args:
        split: "val" 등 데이터 구간
        interval_minutes: 반환할 봉 단위 (1, 5, 10, 15, 30, 60, 240, ...)
    """
    splits = {
        "train": (TRAIN_START, TRAIN_END),
        "val":   (VAL_START,   VAL_END),
        "test":  (TEST_START,  TEST_END),
    }
    if split not in splits:
        raise ValueError(f"split은 {list(splits.keys())} 중 하나여야 합니다")

    start_str, end_str = splits[split]
    start_ms = int(pd.Timestamp(start_str, tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp(end_str,   tz="UTC").timestamp() * 1000)

    result = {}
    for symbol in SYMBOLS:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1m.parquet")
        if not os.path.exists(filepath):
            continue
        try:
            df = pd.read_parquet(filepath)
        except Exception:
            print(f"  {symbol}: parquet 파일 읽기 실패, 스킵")
            continue
        mask = (df["timestamp"] >= start_ms) & (df["timestamp"] < end_ms)
        split_df = df[mask].reset_index(drop=True)

        if interval_minutes != 1:
            split_df = resample_candles(split_df, interval_minutes)
        if len(split_df) > 0:
            result[symbol] = split_df
    return result


# ---------------------------------------------------------------------------
# 백테스트 엔진
# ---------------------------------------------------------------------------

def run_upbit_backtest(strategy, data: dict[str, pd.DataFrame]) -> "UpbitBacktestResult":
    """현물 전략을 data 위에서 시뮬레이션. UpbitBacktestResult 반환."""
    t_start = time.time()

    all_timestamps: set[int] = set()
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

    equity_curve: list[float] = [INITIAL_CAPITAL]
    hourly_returns: list[float] = []
    trade_log: list[tuple] = []
    total_volume = 0.0
    prev_equity = INITIAL_CAPITAL
    history_buffers: dict[str, list] = {symbol: [] for symbol in data}
    pending_signals: list = []   # 이전 봉에서 생성된 시그널 (현재 봉 open으로 실행)

    for ts in timestamps:
        if time.time() - t_start > TIME_BUDGET:
            break

        portfolio.timestamp = ts

        bar_data: dict[str, UpbitBarData] = {}
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

        # 이전 봉 시그널을 현재 봉 open으로 실행 (look-ahead bias 없음)
        for sig in pending_signals:
            if sig.symbol not in bar_data:
                continue
            if sig.target_position < 0:   # 현물: 숏 불가
                continue

            current_price = bar_data[sig.symbol].open   # 다음 봉 open 가격 사용
            current_pos = portfolio.positions.get(sig.symbol, 0.0)
            delta = sig.target_position - current_pos

            if abs(delta) < 1.0:
                continue

            slippage = current_price * SLIPPAGE_BPS / 10000
            exec_price = current_price + slippage if delta > 0 else current_price - slippage
            fee = abs(delta) * TAKER_FEE

            if sig.target_position == 0:
                portfolio.cash -= fee
                total_volume += abs(delta)
                entry = portfolio.entry_prices.get(sig.symbol, exec_price)
                pnl = current_pos * (exec_price - entry) / entry if entry > 0 else 0.0
                portfolio.cash += abs(current_pos) + pnl
                portfolio.positions.pop(sig.symbol, None)
                portfolio.entry_prices.pop(sig.symbol, None)
                trade_log.append(("close", sig.symbol, delta, exec_price, pnl))

            elif current_pos == 0:
                required_cash = abs(sig.target_position) + fee
                if portfolio.cash < required_cash:
                    continue  # 현금 부족 — 주문 스킵
                portfolio.cash -= fee
                total_volume += abs(delta)
                portfolio.cash -= abs(sig.target_position)
                portfolio.positions[sig.symbol] = sig.target_position
                portfolio.entry_prices[sig.symbol] = exec_price
                trade_log.append(("open", sig.symbol, delta, exec_price, 0.0))

            else:
                old_entry = portfolio.entry_prices.get(sig.symbol, exec_price)
                if abs(sig.target_position) < abs(current_pos):
                    portfolio.cash -= fee
                    total_volume += abs(delta)
                    reduced = abs(current_pos) - abs(sig.target_position)
                    pnl = reduced * (exec_price - old_entry) / old_entry if old_entry > 0 else 0.0
                    portfolio.cash += reduced + pnl
                else:
                    added = abs(sig.target_position) - abs(current_pos)
                    required_cash = added + fee
                    if portfolio.cash < required_cash:
                        continue  # 증액 현금 부족 — 주문 스킵
                    portfolio.cash -= fee
                    total_volume += abs(delta)
                    portfolio.cash -= added
                    total = abs(current_pos) + added
                    if total > 0:
                        portfolio.entry_prices[sig.symbol] = (
                            old_entry * abs(current_pos) + exec_price * added
                        ) / total
                portfolio.positions[sig.symbol] = sig.target_position
                trade_log.append(("modify", sig.symbol, delta, exec_price, 0.0))

        # 미실현 손익 계산 (거래 후, on_bar에 전달될 portfolio.equity 업데이트)
        unrealized = sum(
            pos * (bar_data[sym].close - portfolio.entry_prices.get(sym, bar_data[sym].close))
            / portfolio.entry_prices.get(sym, bar_data[sym].close)
            for sym, pos in portfolio.positions.items()
            if sym in bar_data and portfolio.entry_prices.get(sym, 0) > 0
        )
        portfolio.equity = portfolio.cash + sum(abs(v) for v in portfolio.positions.values()) + unrealized

        # 현재 봉 close 기반으로 시그널 생성 — 다음 봉 open에서 실행됨
        try:
            pending_signals = strategy.on_bar(bar_data, portfolio) or []
        except Exception:
            pending_signals = []

        # 자산 재계산 (equity_curve 기록)
        unrealized = sum(
            pos * (bar_data[sym].close - portfolio.entry_prices.get(sym, bar_data[sym].close))
            / portfolio.entry_prices.get(sym, bar_data[sym].close)
            for sym, pos in portfolio.positions.items()
            if sym in bar_data and portfolio.entry_prices.get(sym, 0) > 0
        )
        current_equity = portfolio.cash + sum(abs(v) for v in portfolio.positions.values()) + unrealized
        equity_curve.append(current_equity)

        if prev_equity > 0:
            hourly_returns.append((current_equity - prev_equity) / prev_equity)
        prev_equity = current_equity

        if current_equity < INITIAL_CAPITAL * 0.01:
            break

    t_end = time.time()

    returns = np.array(hourly_returns) if hourly_returns else np.array([0.0])
    eq = np.array(equity_curve)

    sharpe = (returns.mean() / returns.std()) * np.sqrt(HOURS_PER_YEAR) if returns.std() > 0 else 0.0
    final_equity = float(eq[-1]) if len(eq) > 0 else INITIAL_CAPITAL
    total_return_pct = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    peak = np.maximum.accumulate(eq)
    drawdown = (peak - eq) / np.where(peak > 0, peak, 1.0)
    max_drawdown_pct = float(drawdown.max()) * 100

    trade_pnls = [t[4] for t in trade_log if t[0] == "close"]
    num_trades = len(trade_log)
    if trade_pnls:
        wins   = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        win_rate_pct  = len(wins) / len(trade_pnls) * 100
        profit_factor = sum(wins) / max(abs(sum(losses)), 1e-10)
    else:
        win_rate_pct = profit_factor = 0.0

    annual_turnover = total_volume * (HOURS_PER_YEAR / len(timestamps)) if timestamps else 0.0

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
    """Hyperliquid와 동일한 스코어 공식."""
    if result.num_trades < 10:
        return -999.0
    if result.max_drawdown_pct > 50.0:
        return -999.0
    final_equity = result.equity_curve[-1] if result.equity_curve else INITIAL_CAPITAL
    if final_equity < INITIAL_CAPITAL * 0.5:
        return -999.0

    trade_count_factor = min(result.num_trades / 50.0, 1.0)
    drawdown_penalty = max(0.0, result.max_drawdown_pct - 15.0) * 0.05
    turnover_ratio = result.annual_turnover / INITIAL_CAPITAL
    turnover_penalty = max(0.0, turnover_ratio - 500) * 0.001

    return result.sharpe * math.sqrt(trade_count_factor) - drawdown_penalty - turnover_penalty


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=None)
    args = parser.parse_args()
    print(f"캐시 디렉토리: {DATA_DIR}")
    download_upbit_data(args.symbols)
