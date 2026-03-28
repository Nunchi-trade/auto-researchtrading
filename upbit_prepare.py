"""
Upbit 현물 백테스트 시스템. prepare.py의 Upbit 버전.
Usage:
    uv run upbit_prepare.py                    # 데이터 다운로드
    uv run upbit_prepare.py --symbols KRW-BTC  # 특정 심볼만
"""

import os
import time
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone

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

def _download_upbit_candles(market: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Upbit 공개 API로 시간봉 OHLCV 다운로드."""
    all_rows = []
    current_end_ms = end_ms

    while current_end_ms > start_ms:
        to_str = datetime.fromtimestamp(current_end_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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


def download_upbit_data(symbols: list[str] | None = None) -> None:
    """모든 심볼의 시간봉 데이터 다운로드 (캐시 있으면 스킵)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if symbols is None:
        symbols = SYMBOLS

    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp("2025-04-01", tz="UTC").timestamp() * 1000)

    for symbol in symbols:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1h.parquet")
        if os.path.exists(filepath):
            try:
                existing = pd.read_parquet(filepath)
                cached_start = existing["timestamp"].min()
                cached_end   = existing["timestamp"].max()
                if cached_start <= start_ms and cached_end >= end_ms - 3_600_000:
                    print(f"  {symbol}: 이미 {len(existing)} 봉 보유")
                    continue
                print(f"  {symbol}: 캐시 범위 부족, 재다운로드합니다")
            except Exception:
                print(f"  {symbol}: 캐시 파일 손상, 재다운로드합니다")

        print(f"  {symbol}: Upbit API 다운로드 중...")
        try:
            df = _download_upbit_candles(symbol, start_ms, end_ms)
        except requests.RequestException as e:
            print(f"  {symbol}: 네트워크 오류 ({e}), 스킵")
            continue

        if df.empty:
            print(f"  {symbol}: 데이터 없음, 스킵")
            continue

        df.to_parquet(filepath, index=False)
        print(f"  {symbol}: {len(df)} 봉 저장 → {filepath}")


def load_upbit_data(split: str = "val") -> dict[str, pd.DataFrame]:
    """parquet 캐시에서 split 데이터 로드. {symbol: DataFrame} 반환."""
    splits = {"val": (VAL_START, VAL_END)}
    if split not in splits:
        raise ValueError(f"split은 {list(splits.keys())} 중 하나여야 합니다")

    start_str, end_str = splits[split]
    start_ms = int(pd.Timestamp(start_str, tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp(end_str,   tz="UTC").timestamp() * 1000)

    result = {}
    for symbol in SYMBOLS:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1h.parquet")
        if not os.path.exists(filepath):
            continue
        try:
            df = pd.read_parquet(filepath)
        except Exception:
            print(f"  {symbol}: parquet 파일 읽기 실패, 스킵")
            continue
        mask = (df["timestamp"] >= start_ms) & (df["timestamp"] < end_ms)
        split_df = df[mask].reset_index(drop=True)
        if len(split_df) > 0:
            result[symbol] = split_df
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=None)
    args = parser.parse_args()
    print(f"캐시 디렉토리: {DATA_DIR}")
    download_upbit_data(args.symbols)
