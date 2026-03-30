"""
Autotrader backtesting engine. Fixed evaluation harness — DO NOT MODIFY.
Downloads Hyperliquid historical data, runs backtests, computes scores.

Usage:
    python prepare.py                  # download data
    python prepare.py --symbols BTC    # download specific symbols
"""

import os
import time
import math
import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import requests
import pyarrow.parquet as pq

from constants import INITIAL_CAPITAL, MAKER_FEE, TAKER_FEE, SLIPPAGE_BPS
from constants import BENCHMARK_SYMBOLS, HL_INFO_URL

# ---------------------------------------------------------------------------
# Constants (fixed, do not modify)
# ---------------------------------------------------------------------------

TIME_BUDGET = 120  # backtest time budget in seconds (2 minutes)
MAX_LEVERAGE = 20  # max leverage allowed
LOOKBACK_BARS = 500  # history buffer provided to strategy
BAR_INTERVAL = "1h"

SYMBOLS = BENCHMARK_SYMBOLS

# Date splits (UTC timestamps)
TRAIN_START = "2023-06-01"
TRAIN_END = "2024-06-30"
VAL_START = "2024-07-01"
VAL_END = "2025-03-31"
TEST_START = "2025-04-01"
TEST_END = "2025-12-31"

HOURS_PER_YEAR = 8760

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "autotrader")
DATA_DIR = os.path.join(CACHE_DIR, "data")

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class BarData:
    symbol: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    funding_rate: float
    history: pd.DataFrame  # last LOOKBACK_BARS bars


@dataclass
class Signal:
    symbol: str
    target_position: float  # target USD notional (signed: +long, -short)
    order_type: str = "market"


@dataclass
class PortfolioState:
    cash: float
    positions: dict  # symbol -> signed USD notional
    entry_prices: dict  # symbol -> avg entry price
    equity: float = 0.0
    timestamp: int = 0


@dataclass
class BacktestResult:
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
# Data download
# ---------------------------------------------------------------------------

CRYPTOCOMPARE_URL = "https://min-api.cryptocompare.com/data/v2/histohour"


def _download_cryptocompare_candles(
    symbol: str, start_ms: int, end_ms: int
) -> pd.DataFrame:
    """Download hourly OHLCV from CryptoCompare (no geo-restrictions)."""
    all_rows = []
    # CryptoCompare uses 'toTs' (end timestamp in seconds) and returns up to 2000 bars
    current_end = end_ms // 1000
    start_s = start_ms // 1000

    while current_end > start_s:
        params = {
            "fsym": symbol,
            "tsym": "USD",
            "limit": 2000,
            "toTs": current_end,
        }
        resp = requests.get(CRYPTOCOMPARE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        bars = data.get("Data", {}).get("Data", [])
        if not bars:
            break
        for bar in bars:
            ts_s = bar["time"]
            if ts_s < start_s:
                continue
            all_rows.append(
                {
                    "timestamp": ts_s * 1000,
                    "open": float(bar["open"]),
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                    "close": float(bar["close"]),
                    "volume": float(bar.get("volumefrom", 0)),
                }
            )
        # Move window back
        earliest = bars[0]["time"]
        if earliest >= current_end:
            break
        current_end = earliest - 1
        time.sleep(0.3)

    if not all_rows:
        return pd.DataFrame()
    df = (
        pd.DataFrame(all_rows)
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
        .reset_index(drop=True)
    )
    return df


def _download_hl_funding(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Download funding rate history from Hyperliquid."""
    all_rows = []
    current = start_ms
    while current < end_ms:
        body = {
            "type": "fundingHistory",
            "coin": symbol,
            "startTime": current,
            "endTime": min(current + 30 * 24 * 3600 * 1000, end_ms),
        }
        try:
            resp = requests.post(HL_INFO_URL, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            for row in data:
                all_rows.append(
                    {
                        "timestamp": int(row["time"]),
                        "funding_rate": float(row["fundingRate"]),
                    }
                )
            current = int(data[-1]["time"]) + 1
        except Exception:
            break
        time.sleep(0.2)

    if not all_rows:
        return pd.DataFrame(all_rows, columns=pd.Index(["timestamp", "funding_rate"]))
    return pd.DataFrame(all_rows)


def _download_hl_candles(
    symbol: str, interval: str, start_ms: int, end_ms: int
) -> pd.DataFrame:
    """Download OHLCV candles from Hyperliquid."""
    all_rows = []
    current = start_ms
    chunk_ms = 30 * 24 * 3600 * 1000  # 30 days
    while current < end_ms:
        body = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": current,
                "endTime": min(current + chunk_ms, end_ms),
            },
        }
        try:
            resp = requests.post(HL_INFO_URL, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                current += chunk_ms
                continue
            for row in data:
                all_rows.append(
                    {
                        "timestamp": int(row["t"]),
                        "open": float(row["o"]),
                        "high": float(row["h"]),
                        "low": float(row["l"]),
                        "close": float(row["c"]),
                        "volume": float(row["v"]),
                    }
                )
            current = int(data[-1]["t"]) + 3600 * 1000
        except Exception:
            current += chunk_ms
        time.sleep(0.2)
    return pd.DataFrame(all_rows)


def download_data(symbols=None):
    """Download historical OHLCV + funding data for all symbols."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if symbols is None:
        symbols = SYMBOLS

    start_ms = int(pd.Timestamp(TRAIN_START, tz="UTC").asm8.item() / 1_000_000)
    end_ms = int(pd.Timestamp(TEST_END, tz="UTC").asm8.item() / 1_000_000)

    for symbol in symbols:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1h.parquet")
        if os.path.exists(filepath):
            existing = pd.read_parquet(filepath)
            print(f"  {symbol}: already have {len(existing)} bars")
            continue

        print(f"  {symbol}: downloading candles from CryptoCompare...")

        # Use CryptoCompare for reliable historical OHLCV (no geo-restrictions)
        df = _download_cryptocompare_candles(symbol, start_ms, end_ms)
        if len(df) < 100:
            print(
                f"  {symbol}: CryptoCompare insufficient ({len(df)} bars), trying HL..."
            )
            df = _download_hl_candles(symbol, "1h", start_ms, end_ms)

        if df.empty:
            print(f"  {symbol}: NO DATA AVAILABLE, skipping")
            continue

        # Download funding rates
        print(f"  {symbol}: downloading funding rates...")
        funding = _download_hl_funding(symbol, start_ms, end_ms)

        # Merge
        df = (
            df.drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        if not funding.empty:
            funding = funding.drop_duplicates(subset=["timestamp"]).sort_values(
                "timestamp"
            )
            # Merge nearest — funding is every 8h, candles every 1h
            df = pd.merge_asof(df, funding, on="timestamp", direction="backward")
        if "funding_rate" not in df.columns:
            df["funding_rate"] = 0.0
        df["funding_rate"] = df["funding_rate"].fillna(0.0)

        df.to_parquet(filepath, index=False)
        print(f"  {symbol}: saved {len(df)} bars to {filepath}")


def load_data(split: str = "val") -> dict:
    """Load OHLCV+funding data for the given split. Returns {symbol: DataFrame}."""
    splits = {
        "train": (TRAIN_START, TRAIN_END),
        "val": (VAL_START, VAL_END),
        "test": (TEST_START, TEST_END),
    }
    assert split in splits, f"split must be one of {list(splits.keys())}"
    start_str, end_str = splits[split]
    start_ms = int(pd.Timestamp(start_str, tz="UTC").asm8.item() / 1_000_000)
    end_ms = int(pd.Timestamp(end_str, tz="UTC").asm8.item() / 1_000_000)

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


# ---------------------------------------------------------------------------
# Backtesting engine (DO NOT CHANGE)
# ---------------------------------------------------------------------------


def run_backtest(strategy, data: dict) -> BacktestResult:
    """
    Run strategy over data. Returns BacktestResult with full metrics.
    Enforces TIME_BUDGET.
    """
    t_start = time.time()

    # Build unified timeline
    all_timestamps = set()
    for symbol, df in data.items():
        all_timestamps.update(df["timestamp"].tolist())
    timestamps = sorted(all_timestamps)

    if not timestamps:
        return BacktestResult()

    # Index data by (symbol, timestamp) for fast lookup
    indexed = {}
    for symbol, df in data.items():
        indexed[symbol] = df.set_index("timestamp")

    # Portfolio state
    portfolio = PortfolioState(
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

    # History buffers
    history_buffers = {symbol: [] for symbol in data}

    for ts in timestamps:
        elapsed = time.time() - t_start
        if elapsed > TIME_BUDGET:
            break

        portfolio.timestamp = ts

        # Build bar data
        bar_data = {}
        for symbol in data:
            if symbol not in indexed or ts not in indexed[symbol].index:
                continue
            row = indexed[symbol].loc[ts]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]

            # Update history buffer
            bar_dict = {
                "timestamp": ts,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "funding_rate": row.get("funding_rate", 0.0),
            }
            history_buffers[symbol].append(bar_dict)
            if len(history_buffers[symbol]) > LOOKBACK_BARS:
                history_buffers[symbol] = history_buffers[symbol][-LOOKBACK_BARS:]

            hist_df = pd.DataFrame(history_buffers[symbol])

            bar_data[symbol] = BarData(
                symbol=symbol,
                timestamp=ts,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                funding_rate=row.get("funding_rate", 0.0),
                history=hist_df,
            )

        if not bar_data:
            continue

        # Update portfolio equity (mark-to-market)
        unrealized_pnl = 0.0
        for sym, pos_notional in portfolio.positions.items():
            if sym in bar_data:
                current_price = bar_data[sym].close
                entry_price = portfolio.entry_prices.get(sym, current_price)
                if entry_price > 0:
                    price_change = (current_price - entry_price) / entry_price
                    unrealized_pnl += pos_notional * price_change

        portfolio.equity = (
            portfolio.cash
            + sum(abs(v) for v in portfolio.positions.values())
            + unrealized_pnl
        )

        # Apply funding rates (on open positions)
        for sym, pos_notional in list(portfolio.positions.items()):
            if sym in bar_data:
                fr = bar_data[sym].funding_rate
                # Funding: longs pay when positive, shorts receive
                # Applied every 8h, but we have hourly bars so scale by 1/8
                funding_payment = pos_notional * fr / 8.0
                portfolio.cash -= funding_payment

        # Get signals from strategy
        try:
            signals = strategy.on_bar(bar_data, portfolio)
        except Exception:
            signals = []

        # Execute signals
        for sig in signals or []:
            if sig.symbol not in bar_data:
                continue

            current_price = bar_data[sig.symbol].close
            current_pos = portfolio.positions.get(sig.symbol, 0.0)
            delta = sig.target_position - current_pos

            if abs(delta) < 1.0:  # < $1 change, skip
                continue

            # Check leverage constraint
            new_positions = dict(portfolio.positions)
            new_positions[sig.symbol] = sig.target_position
            total_exposure = sum(abs(v) for v in new_positions.values())
            if total_exposure > portfolio.equity * MAX_LEVERAGE:
                continue

            # Apply slippage and fees
            slippage = current_price * SLIPPAGE_BPS / 10000
            fee_rate = TAKER_FEE
            if delta > 0:  # buying
                exec_price = current_price + slippage
            else:  # selling
                exec_price = current_price - slippage

            fee = abs(delta) * fee_rate
            portfolio.cash -= fee
            total_volume += abs(delta)

            # Update position
            if sig.target_position == 0:
                # Closing position — realize PnL
                pnl = 0.0
                if sig.symbol in portfolio.entry_prices:
                    entry = portfolio.entry_prices[sig.symbol]
                    if entry > 0:
                        pnl = current_pos * (exec_price - entry) / entry
                        portfolio.cash += abs(current_pos) + pnl
                    del portfolio.entry_prices[sig.symbol]
                if sig.symbol in portfolio.positions:
                    del portfolio.positions[sig.symbol]
                trade_log.append(
                    (
                        "close",
                        sig.symbol,
                        delta,
                        exec_price,
                        pnl,
                    )
                )
            else:
                if current_pos == 0:
                    # Opening new position
                    portfolio.cash -= abs(sig.target_position)
                    portfolio.positions[sig.symbol] = sig.target_position
                    portfolio.entry_prices[sig.symbol] = exec_price
                    trade_log.append(("open", sig.symbol, delta, exec_price, 0))
                else:
                    # Modifying position
                    old_notional = abs(current_pos)
                    old_entry = portfolio.entry_prices.get(sig.symbol, exec_price)
                    # Realize PnL on reduced portion
                    if abs(sig.target_position) < abs(current_pos):
                        reduced = abs(current_pos) - abs(sig.target_position)
                        if old_entry > 0:
                            pnl = (
                                (current_pos / abs(current_pos))
                                * reduced
                                * (exec_price - old_entry)
                                / old_entry
                            )
                        else:
                            pnl = 0
                        portfolio.cash += reduced + pnl
                    elif abs(sig.target_position) > abs(current_pos):
                        added = abs(sig.target_position) - abs(current_pos)
                        portfolio.cash -= added
                        # Weighted average entry
                        if old_notional + added > 0:
                            new_entry = (
                                old_entry * old_notional + exec_price * added
                            ) / (old_notional + added)
                            portfolio.entry_prices[sig.symbol] = new_entry
                    portfolio.positions[sig.symbol] = sig.target_position
                    trade_log.append(("modify", sig.symbol, delta, exec_price, 0))

        # Recalculate equity after trades
        unrealized_pnl = 0.0
        for sym, pos_notional in portfolio.positions.items():
            if sym in bar_data:
                current_price = bar_data[sym].close
                entry_price = portfolio.entry_prices.get(sym, current_price)
                if entry_price > 0:
                    price_change = (current_price - entry_price) / entry_price
                    unrealized_pnl += pos_notional * price_change

        current_equity = (
            portfolio.cash
            + sum(abs(v) for v in portfolio.positions.values())
            + unrealized_pnl
        )
        equity_curve.append(current_equity)

        # Hourly return
        if prev_equity > 0:
            hourly_returns.append((current_equity - prev_equity) / prev_equity)
        prev_equity = current_equity

        # Liquidation check
        if current_equity < INITIAL_CAPITAL * 0.01:
            break

    t_end = time.time()

    # Compute metrics
    returns = np.array(hourly_returns) if hourly_returns else np.array([0.0])
    eq = np.array(equity_curve)

    # Sharpe ratio (annualized from hourly)
    if returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(HOURS_PER_YEAR)
    else:
        sharpe = 0.0

    # Total return
    final_equity = eq[-1] if len(eq) > 0 else INITIAL_CAPITAL
    total_return_pct = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # Max drawdown
    peak = np.maximum.accumulate(eq)
    drawdown = (peak - eq) / np.where(peak > 0, peak, 1)
    max_drawdown_pct = drawdown.max() * 100

    # Win rate and profit factor
    trade_pnls = [t[4] for t in trade_log if t[0] == "close"]
    num_trades = len(trade_log)
    if trade_pnls:
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        win_rate_pct = len(wins) / len(trade_pnls) * 100 if trade_pnls else 0
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1e-10
        profit_factor = gross_profit / gross_loss
    else:
        win_rate_pct = 0.0
        profit_factor = 0.0

    # Annual turnover
    data_hours = len(timestamps)
    if data_hours > 0:
        annual_turnover = total_volume * (HOURS_PER_YEAR / data_hours)
    else:
        annual_turnover = 0.0

    return BacktestResult(
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


# ---------------------------------------------------------------------------
# Evaluation metric (DO NOT CHANGE — this is the fixed metric)
# ---------------------------------------------------------------------------


def compute_score(result: BacktestResult) -> float:
    """
    Composite risk-adjusted score (HIGHER is better).

    score = sharpe * sqrt(trade_count_factor) - drawdown_penalty - turnover_penalty

    Hard cutoffs for degenerate strategies.
    """
    # Hard cutoffs
    if result.num_trades < 10:
        return -999.0
    if result.max_drawdown_pct > 50.0:
        return -999.0
    final_equity = result.equity_curve[-1] if result.equity_curve else INITIAL_CAPITAL
    if final_equity < INITIAL_CAPITAL * 0.5:
        return -999.0

    # Trade count factor: full credit at 50+ trades
    trade_count_factor = min(result.num_trades / 50.0, 1.0)

    # Drawdown penalty: no penalty below 15%, then 5x per additional percent
    drawdown_penalty = max(0, result.max_drawdown_pct - 15.0) * 0.05

    # Turnover penalty: penalize excessive churning (>500x annual)
    turnover_ratio = (
        result.annual_turnover / INITIAL_CAPITAL if INITIAL_CAPITAL > 0 else 0
    )
    turnover_penalty = max(0, turnover_ratio - 500) * 0.001

    score = (
        result.sharpe * math.sqrt(trade_count_factor)
        - drawdown_penalty
        - turnover_penalty
    )
    return score


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare data for autotrader")
    parser.add_argument(
        "--symbols", nargs="+", default=None, help="Symbols to download (default: all)"
    )
    args = parser.parse_args()

    print(f"Cache directory: {CACHE_DIR}")
    print()

    print("Downloading data...")
    download_data(args.symbols)
    print()
    print("Done! Ready to backtest.")
