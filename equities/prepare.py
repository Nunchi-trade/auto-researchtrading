"""
Equities backtesting engine. Adapted from Nunchi's auto-researchtrading.
Downloads daily OHLCV from Yahoo Finance, runs backtests, computes scores.

Usage:
    python prepare.py                  # download data
    python prepare.py --symbols AAPL   # download specific symbols
"""

import os
import sys
import time
import math
import signal
import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Constants (edit these for your setup)
# ---------------------------------------------------------------------------

TIME_BUDGET = 120  # backtest time budget in seconds (2 minutes)
INITIAL_CAPITAL = 100_000.0  # $100K starting capital
MAKER_FEE = 0.0  # commission-free (Schwab, Fidelity, etc.)
TAKER_FEE = 0.0  # or small if modeling spread
SLIPPAGE_BPS = 1.0  # 1 bps simulated slippage
MAX_LEVERAGE = 2  # 2x margin for equities
LOOKBACK_BARS = 250  # ~1 year of daily history
BAR_INTERVAL = "1d"  # daily bars

SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]

# Date splits (UTC dates)
TRAIN_START = "2020-01-01"
TRAIN_END = "2022-12-31"
VAL_START = "2023-01-01"
VAL_END = "2024-12-31"
TEST_START = "2025-01-01"
TEST_END = "2025-12-31"

TRADING_DAYS_PER_YEAR = 252

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "equities-autotrader")
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
# Data download (Yahoo Finance)
# ---------------------------------------------------------------------------


def download_data(symbols=None):
    """Download daily OHLCV from Yahoo Finance."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if symbols is None:
        symbols = SYMBOLS

    # Download all at once (Yahoo allows bulk)
    all_start = TRAIN_START
    all_end = TEST_END

    for symbol in symbols:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1d.parquet")
        if os.path.exists(filepath):
            existing = pd.read_parquet(filepath)
            print(f"  {symbol}: already have {len(existing)} bars")
            continue

        print(f"  {symbol}: downloading from Yahoo Finance...")

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=all_start, end=all_end, interval="1d")

            if df.empty:
                print(f"  {symbol}: NO DATA AVAILABLE, skipping")
                continue

            # Convert to our format
            df = df.reset_index()
            df = df.rename(
                columns={
                    "Date": "timestamp",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )

            # Convert timestamp to milliseconds (yfinance uses seconds)
            df["timestamp"] = df["timestamp"].astype(np.int64) * 1000

            # Keep only needed columns
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            df = (
                df.drop_duplicates(subset=["timestamp"])
                .sort_values("timestamp")
                .reset_index(drop=True)
            )

            df.to_parquet(filepath, index=False)
            print(f"  {symbol}: saved {len(df)} bars to {filepath}")

        except Exception as e:
            print(f"  {symbol}: ERROR - {e}")
            continue


def load_data(split: str = "val") -> dict:
    """Load OHLCV data for the given split. Returns {symbol: DataFrame}."""
    splits = {
        "train": (TRAIN_START, TRAIN_END),
        "val": (VAL_START, VAL_END),
        "test": (TEST_START, TEST_END),
    }
    assert split in splits, f"split must be one of {list(splits.keys())}"
    start_str, end_str = splits[split]
    start_ms = int(pd.Timestamp(start_str, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_str, tz="UTC").timestamp() * 1000)

    result = {}
    for symbol in SYMBOLS:
        filepath = os.path.join(DATA_DIR, f"{symbol}_1d.parquet")
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
    daily_returns = []
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
                        pnl if "pnl" in dir() else 0,
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

        # Daily return
        if prev_equity > 0:
            daily_returns.append((current_equity - prev_equity) / prev_equity)
        prev_equity = current_equity

        # Liquidation check
        if current_equity < INITIAL_CAPITAL * 0.01:
            break

    t_end = time.time()

    # Compute metrics
    returns = np.array(daily_returns) if daily_returns else np.array([0.0])
    eq = np.array(equity_curve)

    # Sharpe ratio (annualized from daily)
    if returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(TRADING_DAYS_PER_YEAR)
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
    data_days = len(timestamps)
    if data_days > 0:
        annual_turnover = total_volume * (TRADING_DAYS_PER_YEAR / data_days)
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
    parser = argparse.ArgumentParser(description="Prepare equity data for autotrader")
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
