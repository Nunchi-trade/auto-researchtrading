"""Run all benchmark strategies and print leaderboard."""
import os
import sys
import argparse
import importlib
import time

from prepare import load_data, download_data, run_backtest, compute_score, DATA_DIR, SYMBOLS

BENCHMARKS = [
    "benchmarks.buy_and_hold",
    "benchmarks.simple_momentum",
    "benchmarks.mean_reversion",
    "benchmarks.trend_following",
]

parser = argparse.ArgumentParser(description="Run equities benchmarks")
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

data = load_data(args.split, symbols=symbols)
print(f"Loaded {sum(len(df) for df in data.values())} bars across {len(data)} symbols")
print(f"Symbols: {list(data.keys())}\n")

results = []
for name in BENCHMARKS:
    short = name.split(".")[-1]
    try:
        mod = importlib.import_module(name)
        strategy = mod.Strategy(symbols=symbols)
        t0 = time.time()
        result = run_backtest(strategy, data)
        score = compute_score(result)
        dt = time.time() - t0
        results.append((short, score, result.sharpe, result.total_return_pct,
                        result.max_drawdown_pct, result.num_trades, result.win_rate_pct, dt))
        print(f"  {short:25s} score={score:8.4f}  sharpe={result.sharpe:6.3f}  "
              f"ret={result.total_return_pct:7.2f}%  dd={result.max_drawdown_pct:5.2f}%  "
              f"trades={result.num_trades:5d}  wr={result.win_rate_pct:5.1f}%  ({dt:.1f}s)")
    except Exception as e:
        print(f"  {short:25s} CRASHED: {e}")
        results.append((short, -999, 0, 0, 0, 0, 0, 0))

print("\n" + "=" * 80)
print("LEADERBOARD (sorted by score, higher is better)")
print("=" * 80)
results.sort(key=lambda x: x[1], reverse=True)
for i, (name, score, sharpe, ret, dd, trades, wr, dt) in enumerate(results, 1):
    print(f"  {i}. {name:25s} score={score:8.4f}  sharpe={sharpe:6.3f}  "
          f"ret={ret:7.2f}%  dd={dd:5.2f}%  trades={trades:5d}")
