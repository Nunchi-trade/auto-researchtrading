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


def download_upbit_data(symbols: list | None = None) -> None:
    """지정된 심볼의 시간봉 데이터를 다운로드하여 캐시에 저장."""
    os.makedirs(DATA_DIR, exist_ok=True)
    targets = symbols if symbols else SYMBOLS
    start_ms = int(pd.Timestamp(VAL_START, tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp(VAL_END,   tz="UTC").timestamp() * 1000)

    for market in targets:
        out_path = os.path.join(DATA_DIR, f"{market.replace('-', '_')}.parquet")
        print(f"다운로드 중: {market} → {out_path}")
        df = _download_upbit_candles(market, start_ms, end_ms)
        if df.empty:
            print(f"  경고: {market} 데이터 없음")
            continue
        df.to_parquet(out_path, index=False)
        print(f"  저장 완료: {len(df)} 봉")


# load_upbit_data는 Task 2에서 추가됩니다. 지금은 stub만:
def load_upbit_data(split: str = "val") -> dict:
    raise NotImplementedError("Task 2에서 구현 예정")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=None)
    args = parser.parse_args()
    print(f"캐시 디렉토리: {DATA_DIR}")
    download_upbit_data(args.symbols)
