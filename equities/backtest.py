"""
Run backtest. Usage:
    uv run backtest.py                              # default symbols, val split
    uv run backtest.py --symbols AAPL MSFT NVDA     # custom symbols
    uv run backtest.py --split test                  # test split
Imports strategy from strategy.py, runs on specified data, prints metrics.
"""

import os
import time
import argparse
import signal as sig

from prepare import (
    load_data,
    download_data,
    run_backtest,
    compute_score,
    TIME_BUDGET,
    DATA_DIR,
    SYMBOLS,
)


def timeout_handler(signum, frame):
    print("TIMEOUT: backtest exceeded time budget")
    exit(1)


sig.signal(sig.SIGALRM, timeout_handler)
sig.alarm(TIME_BUDGET + 30)

parser = argparse.ArgumentParser(description="Run equities backtest")
parser.add_argument(
    "--symbols", nargs="+", default=None, help="Symbols to trade (default: all)"
)
parser.add_argument(
    "--split", default="val", choices=["train", "val", "test"], help="Data split"
)
args = parser.parse_args()

symbols = args.symbols or SYMBOLS

# Auto-download missing data
missing = [
    s for s in symbols if not os.path.exists(os.path.join(DATA_DIR, f"{s}_1d.parquet"))
]
if missing:
    print(f"Downloading missing data for: {missing}")
    download_data(missing)

t_start = time.time()

from strategy import Strategy

strategy = Strategy(symbols=symbols)
data = load_data(args.split, symbols=symbols)

print(f"Loaded {sum(len(df) for df in data.values())} bars across {len(data)} symbols")
print(f"Symbols: {list(data.keys())}")

result = run_backtest(strategy, data)
score = compute_score(result)

t_end = time.time()

print("---")
print(f"score:              {score:.6f}")
print(f"sharpe:             {result.sharpe:.6f}")
print(f"total_return_pct:   {result.total_return_pct:.6f}")
print(f"max_drawdown_pct:   {result.max_drawdown_pct:.6f}")
print(f"num_trades:         {result.num_trades}")
print(f"win_rate_pct:       {result.win_rate_pct:.6f}")
print(f"profit_factor:      {result.profit_factor:.6f}")
print(f"annual_turnover:    {result.annual_turnover:.2f}")
print(f"backtest_seconds:   {result.backtest_seconds:.1f}")
print(f"total_seconds:      {t_end - t_start:.1f}")
