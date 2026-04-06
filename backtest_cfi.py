"""
Run backtest on CFI data. Usage: uv run backtest_cfi.py
Patches prepare.DATA_DIR to point at cfi_data, then runs standard backtest.
"""

import os
import time
import signal as sig

# Patch DATA_DIR before importing anything else
import prepare
prepare.DATA_DIR = os.path.join(os.path.expanduser("~"), ".cache", "autotrader", "cfi_data")

# Monkey-patch: CFI parquet files have _cfi suffix
_orig_load_data = prepare.load_data

def _load_data_cfi(split="val"):
    import pandas as pd
    splits = {
        "train": (prepare.TRAIN_START, prepare.TRAIN_END),
        "val": (prepare.VAL_START, prepare.VAL_END),
        "test": (prepare.TEST_START, prepare.TEST_END),
    }
    assert split in splits
    start_str, end_str = splits[split]
    start_ms = int(pd.Timestamp(start_str, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_str, tz="UTC").timestamp() * 1000)

    result = {}
    for symbol in prepare.SYMBOLS:
        filepath = os.path.join(prepare.DATA_DIR, f"{symbol}_1h_cfi.parquet")
        if not os.path.exists(filepath):
            # fallback to non-cfi name
            filepath = os.path.join(prepare.DATA_DIR, f"{symbol}_1h.parquet")
        if not os.path.exists(filepath):
            continue
        df = pd.read_parquet(filepath)
        mask = (df["timestamp"] >= start_ms) & (df["timestamp"] < end_ms)
        split_df = df[mask].reset_index(drop=True)
        if len(split_df) > 0:
            result[symbol] = split_df
    return result

prepare.load_data = _load_data_cfi

from prepare import run_backtest, compute_score, TIME_BUDGET

# Timeout guard
def timeout_handler(signum, frame):
    print("TIMEOUT: backtest exceeded time budget")
    exit(1)

sig.signal(sig.SIGALRM, timeout_handler)
sig.alarm(TIME_BUDGET + 30)

t_start = time.time()

from strategy import Strategy

strategy = Strategy()
data = _load_data_cfi("val")

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
