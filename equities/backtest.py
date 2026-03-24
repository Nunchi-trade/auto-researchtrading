"""
Run backtest. Usage:
    uv run backtest.py                              # default symbols, val split
    uv run backtest.py --symbols AAPL MSFT NVDA     # custom symbols
    uv run backtest.py --split test                  # test split
    uv run backtest.py --scenario fed_emergency_hike # MiroFish scenario
    uv run backtest.py --stress-test                 # all scenarios + real data
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
parser.add_argument(
    "--scenario", type=str, default=None,
    help="MiroFish scenario name (e.g., fed_emergency_hike)",
)
parser.add_argument(
    "--stress-test", action="store_true",
    help="Run on real data + all MiroFish scenarios, print composite score",
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


def run_single(data, label=""):
    """Run a single backtest and print results."""
    strategy = Strategy(symbols=symbols)
    result = run_backtest(strategy, data)
    score = compute_score(result)
    if label:
        print(f"\n--- {label} ---")
    else:
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
    return score


if args.stress_test:
    # Run on real data + all MiroFish scenarios
    from mirofish import ScenarioBridge, ScenarioManager

    mgr = ScenarioManager()
    bridge = ScenarioBridge()  # fallback mode (no MiroFish client needed for cached/synthetic)

    # Real data first
    data = load_data(args.split, symbols=symbols)
    print(f"Loaded {sum(len(df) for df in data.values())} bars across {len(data)} symbols")
    print(f"Symbols: {list(data.keys())}")
    real_score = run_single(data, "REAL DATA")

    # Scenarios
    scenario_scores = {}
    for name in mgr.list_scenarios():
        try:
            scenario_data = bridge.generate(name, symbols, args.split)
            if scenario_data:
                s = run_single(scenario_data, f"SCENARIO: {name}")
                scenario_scores[name] = s
        except Exception as e:
            print(f"\n--- SCENARIO: {name} ---")
            print(f"  ERROR: {e}")
            scenario_scores[name] = -5.0

    # Composite score
    valid_scores = [s for s in scenario_scores.values() if s > -999]
    if valid_scores:
        scenario_avg = sum(valid_scores) / len(valid_scores)
    else:
        scenario_avg = 0.0

    # Penalize -999 scenarios
    penalty_count = sum(1 for s in scenario_scores.values() if s <= -999)
    penalty = penalty_count * -5.0

    composite = 0.6 * real_score + 0.4 * scenario_avg + penalty

    t_end = time.time()
    print("\n" + "=" * 60)
    print("STRESS TEST SUMMARY")
    print("=" * 60)
    print(f"  Real data score:    {real_score:.4f}")
    print(f"  Scenario average:   {scenario_avg:.4f}")
    if penalty_count > 0:
        print(f"  Penalty (-999s):    {penalty:.4f} ({penalty_count} scenarios)")
    print(f"  Composite score:    {composite:.4f}")
    print(f"  Total time:         {t_end - t_start:.1f}s")
    print()
    for name, s in sorted(scenario_scores.items(), key=lambda x: x[1], reverse=True):
        print(f"  {name:25s} {s:8.4f}")

    # Print composite as score: line for grep compatibility
    print(f"\nscore:              {composite:.6f}")

elif args.scenario:
    # Run on a single MiroFish scenario
    from mirofish import ScenarioBridge

    bridge = ScenarioBridge()
    data = bridge.generate(args.scenario, symbols, args.split)
    print(f"Loaded scenario '{args.scenario}': {sum(len(df) for df in data.values())} bars across {len(data)} symbols")
    print(f"Symbols: {list(data.keys())}")
    score = run_single(data)
    t_end = time.time()
    print(f"total_seconds:      {t_end - t_start:.1f}")

else:
    # Normal backtest on real data
    data = load_data(args.split, symbols=symbols)
    print(f"Loaded {sum(len(df) for df in data.values())} bars across {len(data)} symbols")
    print(f"Symbols: {list(data.keys())}")
    score = run_single(data)
    t_end = time.time()
    print(f"total_seconds:      {t_end - t_start:.1f}")
