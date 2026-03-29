"""15m Strategy Parameter Tuning — comprehensive sweep over all 36 parameters.

Phases:
  1. Single-parameter sweeps (each param independently, subsampled)
  1b. Re-validate phase 1 winners on full data
  2. Secondary sweeps (paired params + lookback windows, subsampled)
  2b. Re-validate phase 2 winners on full data
  3. Adaptive multi-parameter grid (subsampled, then top-10 on full data)
  4. Automatic OOS validation of best candidate

Scoring:
  score = (Ret/BPP) / DD * trade_confidence * PF_bonus
  BPP = BASE_POSITION_PCT (leverage normalization)
  Prevents leverage inflation from dominating signal quality comparison.
  trade_confidence = min(num_closes / 20, 1.0)
  PF_bonus = 1 + max(0, PF - 2) * 0.1
"""

import sys
import time
import itertools
import json
import argparse
import multiprocessing as mp
from pathlib import Path
import numpy as np
import pandas as pd

_this_dir = Path(__file__).resolve().parent  # backtest/
_bot_root = _this_dir.parent  # live_trading_bot/
for _p in (_this_dir, _bot_root):
    sp = str(_p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from backtest_interval import run_backtest_1m, load_data
import strategies.strategy_15m as s15m

# ---------------------------------------------------------------------------
# DEFAULTS
# ---------------------------------------------------------------------------
DEFAULTS = {
    "SHORT_WINDOW": 24,
    "MED_WINDOW": 48,
    "MED2_WINDOW": 96,
    "LONG_WINDOW": 144,
    "EMA_FAST": 28,
    "EMA_SLOW": 104,
    "RSI_PERIOD": 32,
    "RSI_BULL": 50,
    "RSI_BEAR": 50,
    "RSI_OVERBOUGHT": 69,
    "RSI_OVERSOLD": 31,
    "MACD_FAST": 56,
    "MACD_SLOW": 92,
    "MACD_SIGNAL": 36,
    "BB_PERIOD": 28,
    "FUNDING_LOOKBACK": 96,
    "FUNDING_BOOST": 0.0,
    "BASE_POSITION_PCT": 0.08,
    "VOL_LOOKBACK": 144,
    "TARGET_VOL": 0.015,
    "ATR_LOOKBACK": 96,
    "ATR_STOP_MULT": 5.5,
    "TAKE_PROFIT_PCT": 99.0,
    "BASE_THRESHOLD": 0.012,
    "BTC_OPPOSE_THRESHOLD": -99.0,
    "PYRAMID_THRESHOLD": 0.015,
    "PYRAMID_SIZE": 0.0,
    "CORR_LOOKBACK": 288,
    "HIGH_CORR_THRESHOLD": 99.0,
    "DD_REDUCE_THRESHOLD": 99.0,
    "DD_REDUCE_SCALE": 0.5,
    "COOLDOWN_BARS": 8,
    "MIN_VOTES": 4,
    "THRESHOLD_MIN": 0.005,
    "THRESHOLD_MAX": 0.020,
    "BB_COMPRESS_PCTILE": 90,
}

INT_PARAMS = {
    "SHORT_WINDOW",
    "MED_WINDOW",
    "MED2_WINDOW",
    "LONG_WINDOW",
    "EMA_FAST",
    "EMA_SLOW",
    "RSI_PERIOD",
    "RSI_BULL",
    "RSI_BEAR",
    "RSI_OVERBOUGHT",
    "RSI_OVERSOLD",
    "MACD_FAST",
    "MACD_SLOW",
    "MACD_SIGNAL",
    "BB_PERIOD",
    "FUNDING_LOOKBACK",
    "VOL_LOOKBACK",
    "ATR_LOOKBACK",
    "COOLDOWN_BARS",
    "MIN_VOTES",
    "CORR_LOOKBACK",
    "BB_COMPRESS_PCTILE",
}

BAR_COUNT_PARAMS = {
    "SHORT_WINDOW",
    "MED_WINDOW",
    "MED2_WINDOW",
    "LONG_WINDOW",
    "EMA_FAST",
    "EMA_SLOW",
    "RSI_PERIOD",
    "MACD_FAST",
    "MACD_SLOW",
    "MACD_SIGNAL",
    "BB_PERIOD",
    "FUNDING_LOOKBACK",
    "VOL_LOOKBACK",
    "ATR_LOOKBACK",
    "COOLDOWN_BARS",
    "CORR_LOOKBACK",
}


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------
def score_result(r: dict) -> float:
    ret = r["total_return_pct"]
    dd = max(r["max_drawdown_pct"], 0.01)

    bpp = r.get("params", {}).get("BASE_POSITION_PCT", DEFAULTS["BASE_POSITION_PCT"])
    norm_ret = ret / max(bpp, 0.1)
    ret_dd = norm_ret / dd

    num_closes = r.get("num_closes", r.get("num_trades", 0))
    trade_confidence = min(num_closes / 20.0, 1.0)

    pf = r.get("profit_factor", 1.0)
    pf_bonus = 1.0 + max(0, pf - 2) * 0.1

    return ret_dd * trade_confidence * pf_bonus


# ---------------------------------------------------------------------------
# DATA SUBSAMPLING — take every Nth bar for fast screening
# ---------------------------------------------------------------------------
def subsample_data(data: dict, every_n: int = 4) -> dict:
    """Take every Nth timestamp from each symbol's DataFrame.

    every_n=4 on 15m data gives ~1h effective resolution.
    Reduces bar count (and backtest time) by ~4x.
    """
    if every_n <= 1:
        return data
    return {sym: df.iloc[::every_n].reset_index(drop=True) for sym, df in data.items()}


# ---------------------------------------------------------------------------
# SINGLE-PARAMETER SWEEPS
# ---------------------------------------------------------------------------
SINGLE_SWEEPS = [
    (
        "BASE_POSITION_PCT",
        {"BASE_POSITION_PCT": [0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20]},
    ),
    (
        "ATR_STOP_MULT",
        {"ATR_STOP_MULT": [3.0, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 8.0, 10.0]},
    ),
    ("COOLDOWN_BARS", {"COOLDOWN_BARS": [2, 4, 6, 8, 12, 16, 20]}),
    ("MIN_VOTES", {"MIN_VOTES": [3, 4, 5, 6]}),
    ("BASE_THRESHOLD", {"BASE_THRESHOLD": [0.005, 0.008, 0.010, 0.012, 0.015, 0.020]}),
    (
        "RSI_OB_OS",
        [
            {"RSI_OVERBOUGHT": 65, "RSI_OVERSOLD": 35},
            {"RSI_OVERBOUGHT": 69, "RSI_OVERSOLD": 31},
            {"RSI_OVERBOUGHT": 72, "RSI_OVERSOLD": 28},
            {"RSI_OVERBOUGHT": 75, "RSI_OVERSOLD": 25},
            {"RSI_OVERBOUGHT": 80, "RSI_OVERSOLD": 20},
        ],
    ),
]

# ---------------------------------------------------------------------------
# SECONDARY SWEEPS
# ---------------------------------------------------------------------------
SECONDARY_SWEEPS = [
    ("BB_COMPRESS_PCTILE", {"BB_COMPRESS_PCTILE": [80, 85, 90, 95]}),
    (
        "THRESHOLD_MIN_MAX",
        [
            {"THRESHOLD_MIN": 0.003, "THRESHOLD_MAX": 0.015},
            {"THRESHOLD_MIN": 0.005, "THRESHOLD_MAX": 0.020},
            {"THRESHOLD_MIN": 0.008, "THRESHOLD_MAX": 0.025},
            {"THRESHOLD_MIN": 0.010, "THRESHOLD_MAX": 0.030},
        ],
    ),
    ("RSI_PERIOD", {"RSI_PERIOD": [24, 28, 32, 40, 48]}),
    (
        "RSI_BULL_BEAR",
        [
            {"RSI_BULL": 45, "RSI_BEAR": 55},
            {"RSI_BULL": 50, "RSI_BEAR": 50},
            {"RSI_BULL": 55, "RSI_BEAR": 45},
        ],
    ),
    ("SHORT_WINDOW", {"SHORT_WINDOW": [12, 18, 24, 32, 40]}),
    ("MED_WINDOW", {"MED_WINDOW": [36, 48, 60, 72]}),
    (
        "EMA_FAST_SLOW",
        [
            {"EMA_FAST": 20, "EMA_SLOW": 80},
            {"EMA_FAST": 24, "EMA_SLOW": 96},
            {"EMA_FAST": 28, "EMA_SLOW": 104},
            {"EMA_FAST": 32, "EMA_SLOW": 120},
            {"EMA_FAST": 36, "EMA_SLOW": 140},
        ],
    ),
    (
        "MACD_PARAMS",
        [
            {"MACD_FAST": 48, "MACD_SLOW": 80, "MACD_SIGNAL": 28},
            {"MACD_FAST": 56, "MACD_SLOW": 92, "MACD_SIGNAL": 36},
            {"MACD_FAST": 64, "MACD_SLOW": 104, "MACD_SIGNAL": 40},
        ],
    ),
    ("BB_PERIOD", {"BB_PERIOD": [20, 24, 28, 36, 48]}),
    ("VOL_LOOKBACK", {"VOL_LOOKBACK": [96, 120, 144, 192, 240]}),
]


# ---------------------------------------------------------------------------
# PARAMETER MANAGEMENT
# ---------------------------------------------------------------------------
def reset_params():
    for k, v in DEFAULTS.items():
        setattr(s15m, k, v)


def set_params(overrides: dict, subsample_factor: int = 1):
    # Reset to (possibly scaled) defaults
    for k, v in DEFAULTS.items():
        if subsample_factor > 1 and k in BAR_COUNT_PARAMS:
            setattr(s15m, k, max(1, int(round(v / subsample_factor))))
        else:
            setattr(s15m, k, v)
    # Apply (possibly scaled) overrides
    for k, v in overrides.items():
        if subsample_factor > 1 and k in BAR_COUNT_PARAMS:
            v = max(1, int(round(v / subsample_factor)))
        if k in INT_PARAMS:
            v = int(v)
        setattr(s15m, k, v)


def run_once(data, overrides: dict, subsample_factor: int = 1) -> dict:
    set_params(overrides, subsample_factor=subsample_factor)
    strategy = s15m.Strategy()
    result = run_backtest_1m(strategy, data, "15m")
    if "error" in result:
        return result
    result["params"] = dict(overrides)
    result["_score"] = score_result(result)
    return result


# Global for multiprocessing workers (set before Pool creation, inherited via fork)
_mp_data = None
_mp_subsample = 1


def _mp_run_once(overrides: dict) -> dict:
    """Worker function for parallel sweeps. Uses forked copy of _mp_data."""
    set_params(overrides, subsample_factor=_mp_subsample)
    strategy = s15m.Strategy()
    result = run_backtest_1m(strategy, _mp_data, "15m")
    if "error" in result:
        result["params"] = dict(overrides)
        result["_score"] = -1.0
        return result
    result["params"] = dict(overrides)
    result["_score"] = score_result(result)
    return result


# ---------------------------------------------------------------------------
# SWEEP RUNNER
# ---------------------------------------------------------------------------
def run_sweep(
    data, name: str, param_grid, n_workers: int = 1, subsample_factor: int = 1
) -> list[dict]:
    if isinstance(param_grid, list):
        combos = [dict(p) for p in param_grid]
    else:
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combos = [dict(zip(keys, combo)) for combo in itertools.product(*values)]
    total = len(combos)
    print(f"  Running {total} combinations for {name} ({n_workers} workers)...")
    t0 = time.time()

    if n_workers > 1 and total > 1:
        global _mp_data, _mp_subsample
        _mp_data = data
        _mp_subsample = subsample_factor
        timed_out = False
        try:
            with mp.Pool(processes=n_workers) as pool:
                async_result = pool.map_async(
                    _mp_run_once, combos, chunksize=max(1, total // (n_workers * 4))
                )
                timeout = max(300, total * 10)
                while not async_result.ready():
                    async_result.wait(timeout=5)
                    if async_result.ready():
                        break
                    elapsed = time.time() - t0
                    print(
                        f"\r  Pool running... {elapsed:.0f}s/{timeout}s   ",
                        end="",
                        flush=True,
                    )
                    if elapsed > timeout:
                        print(
                            f"\n  [POOL TIMEOUT] after {timeout}s, "
                            f"falling back to sequential"
                        )
                        pool.terminate()
                        timed_out = True
                        break
                if timed_out:
                    raw = []
                    for overrides in combos:
                        try:
                            r = run_once(
                                data, overrides, subsample_factor=subsample_factor
                            )
                            if "error" not in r:
                                raw.append(r)
                        except Exception:
                            pass
                else:
                    raw = async_result.get()
            results = [r for r in raw if r.get("_score", -1) >= 0]
            skipped = [r for r in raw if r.get("_score", -1) < 0]
            for r in skipped:
                print(f"  [SKIP] {r.get('params', {})}")
        except Exception as e:
            print(f"  [POOL ERROR] {e}, falling back to sequential")
            results = []
            for overrides in combos:
                try:
                    r = run_once(data, overrides, subsample_factor=subsample_factor)
                    if "error" not in r:
                        results.append(r)
                except Exception:
                    pass
    else:
        results = []
        for i, overrides in enumerate(combos):
            try:
                r = run_once(data, overrides, subsample_factor=subsample_factor)
                if "error" not in r:
                    results.append(r)
                else:
                    print(f"  [SKIP] {overrides}: {r['error']}")
            except Exception as e:
                print(f"  [ERROR] {overrides}: {e}")
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (total - i - 1) if i > 0 else 0
            print(
                f"\r  Progress: {(i + 1) / total * 100:5.1f}%  "
                f"({i + 1}/{total})  ETA: {eta:.0f}s   ",
                end="",
                flush=True,
            )

    elapsed = time.time() - t0
    print(f"\n  Completed in {elapsed:.1f}s ({elapsed / max(total, 1):.1f}s/combo)")
    return results


# ---------------------------------------------------------------------------
# RESULTS PRINTING
# ---------------------------------------------------------------------------
def print_results(results: list[dict], name: str, top_n: int = 5):
    if not results:
        print(f"  No valid results for {name}")
        return None

    results.sort(key=lambda x: x["_score"], reverse=True)

    print(f"\n{'=' * 90}")
    print(f"SWEEP: {name}")
    print(f"{'=' * 90}")
    header = (
        f"{'Return%':>10} {'DD%':>8} {'Ret/DD':>8} {'PF':>8} "
        f"{'WR%':>6} {'Trades':>7} {'Score':>8} Params"
    )
    print(header)
    print("-" * 90)
    for r in results[:top_n]:
        params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
        print(
            f"{r['total_return_pct']:>+10.2f} {r['max_drawdown_pct']:>8.2f} "
            f"{r['total_return_pct'] / max(r['max_drawdown_pct'], 0.01):>8.2f} "
            f"{r['profit_factor']:>8.2f} "
            f"{r['win_rate_pct']:>5.1f}% {r['num_trades']:>7d} "
            f"{r['_score']:>8.2f} {params_str}"
        )
    if len(results) > top_n:
        print(f"  ... ({len(results) - top_n} more)")
    best = results[0]
    best_params = ", ".join(f"{k}={v}" for k, v in best["params"].items())
    print(
        f"\nBEST: {best_params} "
        f"-> Score={best['_score']:.2f}, Ret/DD={best['total_return_pct'] / max(best['max_drawdown_pct'], 0.01):.2f}, "
        f"PF={best['profit_factor']:.2f}, WR={best['win_rate_pct']:.1f}%"
    )
    print()
    return best


# ---------------------------------------------------------------------------
# RE-VALIDATE — run top-N subsampled results on full data to confirm ranking
# ---------------------------------------------------------------------------
def revalidate(full_data: dict, results: list[dict], top_n: int = 3) -> list[dict]:
    """Re-run the top N results on full data, return re-scored results."""
    candidates = sorted(results, key=lambda x: x["_score"], reverse=True)[:top_n]
    print(f"  Re-validating top {len(candidates)} on full data...")
    validated = []
    for i, r in enumerate(candidates):
        rv = run_once(full_data, r["params"])
        if "error" not in rv:
            validated.append(rv)
            subsampled_score = r["_score"]
            full_score = rv["_score"]
            print(
                f"    [{i + 1}] subsampled={subsampled_score:.2f} -> full={full_score:.2f}  "
                f"Ret={rv['total_return_pct']:+.1f}% DD={rv['max_drawdown_pct']:.1f}%"
            )
    return validated


def forward_stepwise_accumulate(
    full_data: dict, all_validated: list[dict], initial_params: dict | None = None
) -> tuple[dict, float]:
    """Forward stepwise: test each sweep's best params incrementally.

    For each validated result (sorted by score descending), merge its
    params into the current best and test jointly. Only keep changes
    that improve the joint score.

    Returns (best_params_dict, best_score).
    """
    if initial_params is None:
        initial_params = DEFAULTS.copy()

    baseline = run_once(full_data, initial_params)
    if "error" in baseline:
        return initial_params, 0.0

    current_params = initial_params.copy()
    current_score = baseline["_score"]
    print(f"  Baseline score: {current_score:.2f}")

    seen = set()
    unique = []
    for r in sorted(all_validated, key=lambda x: x["_score"], reverse=True):
        key = tuple(sorted(r["params"].items()))
        if key not in seen:
            seen.add(key)
            unique.append(r)

    candidates = []
    for r in unique:
        changes = {k: v for k, v in r["params"].items() if v != DEFAULTS.get(k)}
        if changes:
            candidates.append(r)

    print(f"  Testing {len(candidates)} non-default sweep results incrementally...")

    for r in candidates:
        test_params = current_params.copy()
        test_params.update(r["params"])

        test_result = run_once(full_data, test_params)
        if "error" in test_result:
            params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
            print(f"  [ERROR] {params_str}")
            continue

        test_score = test_result["_score"]
        params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())

        if test_score > current_score:
            print(f"  [ACCEPT] {params_str} -> {current_score:.2f} -> {test_score:.2f}")
            current_params = test_params
            current_score = test_score
        else:
            print(
                f"  [REJECT] {params_str} -> {test_score:.2f} (need > {current_score:.2f})"
            )

    return current_params, current_score


# ---------------------------------------------------------------------------
# ADAPTIVE MULTI-GRID
# ---------------------------------------------------------------------------
# Params to include in adaptive grid, with value generators
ADAPTIVE_GRID_PARAMS = {
    "RSI_PERIOD": lambda v: sorted(
        set([max(8, v - 8), max(8, v - 4), v, v + 4, v + 8])
    ),
    "BASE_POSITION_PCT": lambda v: sorted(
        set([round(max(0.02, v * 0.5), 3), round(v, 3), round(v * 1.5, 3)])
    ),
    "ATR_STOP_MULT": lambda v: sorted(
        set([max(2.0, round(v - 1.5, 1)), round(v, 1), round(v + 1.5, 1)])
    ),
    "COOLDOWN_BARS": lambda v: sorted(set([max(2, v - 4), v, v + 4, v + 8])),
    "MIN_VOTES": lambda v: sorted(set([max(2, v - 1), v, min(6, v + 1)])),
    "BASE_THRESHOLD": lambda v: sorted(
        set([round(v * 0.7, 4), round(v, 4), round(v * 1.3, 4)])
    ),
}


def build_adaptive_grid(best_params: dict) -> dict:
    """Build adaptive grid including params that differ from defaults.

    ALWAYS includes RSI_PERIOD (most impactful parameter).
    Includes other params that changed from defaults.
    Limits to 6 params max to keep grid size manageable.
    """
    grid = {}

    changes = {k: v for k, v in best_params.items() if v != DEFAULTS.get(k)}

    for param, grid_fn in ADAPTIVE_GRID_PARAMS.items():
        # Always include RSI_PERIOD, include others only if they changed
        if param == "RSI_PERIOD" or param in changes:
            val = best_params.get(param, DEFAULTS[param])
            if param in INT_PARAMS:
                val = int(val)
            grid[param] = grid_fn(val)

    # If nothing qualified (shouldn't happen), use RSI_PERIOD default grid
    if not grid:
        grid["RSI_PERIOD"] = [24, 28, 32, 40]

    return grid


# ---------------------------------------------------------------------------
# OOS VALIDATION
# ---------------------------------------------------------------------------
def run_oos(data, overrides: dict, train_pct: float = 0.6) -> dict:
    all_ts = set()
    for df in data.values():
        all_ts.update(df["timestamp"].tolist())
    timestamps = sorted(all_ts)
    split_idx = int(len(timestamps) * train_pct)
    split_ts = timestamps[split_idx]

    train_data = {}
    oos_data = {}
    for symbol, df in data.items():
        train_df = df[df["timestamp"] <= split_ts].copy()
        oos_df = df[df["timestamp"] > split_ts].copy()
        if len(train_df) > 0:
            train_data[symbol] = train_df
        if len(oos_df) > 0:
            oos_data[symbol] = oos_df

    print(f"  Train bars: {sum(len(df) for df in train_data.values())}")
    print(f"  OOS bars:   {sum(len(df) for df in oos_data.values())}")

    set_params(overrides)
    is_result = run_backtest_1m(s15m.Strategy(), train_data, "15m")
    set_params(overrides)
    oos_result = run_backtest_1m(s15m.Strategy(), oos_data, "15m")

    is_result["final_equity"] = is_result.get("final_equity", 10000.0)
    oos_result["final_equity"] = oos_result.get("final_equity", 10000.0)
    is_result["params"] = dict(overrides)
    oos_result["params"] = dict(overrides)
    is_score = score_result(is_result)
    oos_score = score_result(oos_result)

    return {
        "params": dict(overrides),
        "IS_return": is_result.get("total_return_pct", 0),
        "IS_dd": is_result.get("max_drawdown_pct", 0),
        "IS_pf": is_result.get("profit_factor", 0),
        "IS_wr": is_result.get("win_rate_pct", 0),
        "IS_trades": is_result.get("num_trades", 0),
        "IS_score": is_score,
        "OOS_return": oos_result.get("total_return_pct", 0),
        "OOS_dd": oos_result.get("max_drawdown_pct", 0),
        "OOS_pf": oos_result.get("profit_factor", 0),
        "OOS_wr": oos_result.get("win_rate_pct", 0),
        "OOS_trades": oos_result.get("num_trades", 0),
        "OOS_score": oos_score,
        "degradation": (is_score - oos_score) / is_score
        if is_score > 0
        else float("inf"),
    }


def print_oos(result: dict):
    print(f"\n{'=' * 90}")
    print("OUT-OF-SAMPLE VALIDATION")
    print(f"{'=' * 90}")
    params_str = ", ".join(f"{k}={v}" for k, v in result["params"].items())
    print(f"Params: {params_str}")
    print(
        f"{'':>20} {'Return%':>10} {'DD%':>8} {'PF':>8} "
        f"{'WR%':>6} {'Trades':>7} {'Score':>8}"
    )
    print("-" * 90)
    print(
        f"{'IS (60%)':>20} {result['IS_return']:>+10.2f} {result['IS_dd']:>8.2f} "
        f"{result['IS_pf']:>8.2f} {result['IS_wr']:>5.1f}% {result['IS_trades']:>7d} "
        f"{result['IS_score']:>8.2f}"
    )
    print(
        f"{'OOS (40%)':>20} {result['OOS_return']:>+10.2f} {result['OOS_dd']:>8.2f} "
        f"{result['OOS_pf']:>8.2f} {result['OOS_wr']:>5.1f}% {result['OOS_trades']:>7d} "
        f"{result['OOS_score']:>8.2f}"
    )
    deg = result["degradation"]
    if deg < 0.3:
        verdict = "PASS"
    elif deg < 0.6:
        verdict = "CAUTION"
    else:
        verdict = "FAIL — likely overfit"
    print(f"\n  Degradation: {deg * 100:.1f}%  -> {verdict}")
    print()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="15m Strategy Parameter Tuning")
    parser.add_argument(
        "--phase",
        choices=["single", "secondary", "multi", "oos", "all"],
        default="all",
    )
    parser.add_argument("--multi-grid", type=str, default=None)
    parser.add_argument("--oos-params", type=str, default=None)
    parser.add_argument(
        "--subsample",
        type=int,
        default=4,
        help="Take every Nth bar for screening (default=4, ~4x speedup). Use 1 for full data.",
    )
    parser.add_argument(
        "--revalidate-top",
        type=int,
        default=2,
        help="Re-validate top N candidates per sweep on full data (default=2)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=mp.cpu_count(),
        help=f"Parallel workers for sweeps (default={mp.cpu_count()})",
    )
    args = parser.parse_args()

    full_data = load_data(
        interval="15m", data_dir=str(_bot_root / "backtest_data" / "15m_candles")
    )
    if not full_data:
        print("ERROR: No data loaded")
        sys.exit(1)
    total_bars = sum(len(df) for df in full_data.values())
    print(
        f"Loaded {total_bars} bars across {len(full_data)} symbols: {list(full_data.keys())}"
    )

    screen_data = subsample_data(full_data, args.subsample)
    screen_bars = sum(len(df) for df in screen_data.values())
    speedup = total_bars / screen_bars if screen_bars > 0 else 1
    print(
        f"Screening data: {screen_bars} bars ({speedup:.1f}x speedup, every {args.subsample}th bar)"
    )
    print(f"Re-validating top {args.revalidate_top} per sweep on full data")
    print(f"Using {args.workers} parallel workers")

    best_params_accumulator = DEFAULTS.copy()
    best_overall_result = None
    all_phase_results = []

    # ---- PHASE 1: SINGLE-PARAMETER SWEEPS (screen on subsampled) ----
    if args.phase in ("single", "all"):
        print("\n" + "=" * 90)
        print("PHASE 1: SINGLE-PARAMETER SWEEPS (subsampled)")
        print("=" * 90)
        for name, grid in SINGLE_SWEEPS:
            results = run_sweep(
                screen_data,
                name,
                grid,
                n_workers=args.workers,
                subsample_factor=args.subsample,
            )
            best_screen = print_results(results, name)
            if results and args.subsample > 1:
                validated = revalidate(full_data, results, top_n=args.revalidate_top)
                if validated:
                    print_results(
                        validated, f"{name} (full data)", top_n=len(validated)
                    )
                    all_phase_results.extend(validated)
                    for r in validated:
                        if (
                            best_overall_result is None
                            or r["_score"] > best_overall_result["_score"]
                        ):
                            best_overall_result = r
            elif best_screen:
                all_phase_results.append(best_screen)
                if (
                    best_overall_result is None
                    or best_screen["_score"] > best_overall_result["_score"]
                ):
                    best_overall_result = best_screen

    # ---- PHASE 2: SECONDARY SWEEPS (screen on subsampled) ----
    if args.phase in ("secondary", "all"):
        print("\n" + "=" * 90)
        print("PHASE 2: SECONDARY SWEEPS (subsampled)")
        print("=" * 90)
        for name, grid in SECONDARY_SWEEPS:
            results = run_sweep(
                screen_data,
                name,
                grid,
                n_workers=args.workers,
                subsample_factor=args.subsample,
            )
            best_screen = print_results(results, name)
            if results and args.subsample > 1:
                validated = revalidate(full_data, results, top_n=args.revalidate_top)
                if validated:
                    print_results(
                        validated, f"{name} (full data)", top_n=len(validated)
                    )
                    all_phase_results.extend(validated)
                    for r in validated:
                        if (
                            best_overall_result is None
                            or r["_score"] > best_overall_result["_score"]
                        ):
                            best_overall_result = r
            elif best_screen:
                all_phase_results.append(best_screen)
                if (
                    best_overall_result is None
                    or best_screen["_score"] > best_overall_result["_score"]
                ):
                    best_overall_result = best_screen

    # ---- FORWARD STEPWISE ACCUMULATOR ----
    if best_overall_result is not None and args.phase in ("secondary", "multi", "all"):
        print("\n" + "=" * 90)
        print("FORWARD STEPWISE ACCUMULATOR")
        print("=" * 90)
        stepwise_params, stepwise_score = forward_stepwise_accumulate(
            full_data, all_phase_results
        )
        changes = {k: v for k, v in stepwise_params.items() if v != DEFAULTS.get(k)}
        print(f"  Final stepwise changes from defaults: {changes}")
        print(f"  Stepwise score: {stepwise_score:.2f}")
        print(f"  Best single result score: {best_overall_result['_score']:.2f}")
        if best_overall_result and stepwise_score < best_overall_result["_score"]:
            print(f"  -> Stepwise WORSE than best single, using best single params")
            best_params_accumulator = best_overall_result["params"].copy()
            for k, v in DEFAULTS.items():
                if k not in best_params_accumulator:
                    best_params_accumulator[k] = v
        else:
            print(f"  -> Stepwise OK, keeping combined params")
            best_params_accumulator = stepwise_params.copy()

    # ---- PHASE 3: ADAPTIVE MULTI-PARAMETER GRID ----
    if args.phase in ("multi", "all"):
        if args.multi_grid:
            grid = json.loads(args.multi_grid)
        else:
            grid = build_adaptive_grid(best_params_accumulator)

        total_combos = 1
        for v in grid.values():
            total_combos *= len(v)

        print("\n" + "=" * 90)
        print("PHASE 3: ADAPTIVE MULTI-PARAMETER GRID")
        print("=" * 90)
        print(f"  Grid derived from phase 1-2 winners:")
        for k, v in grid.items():
            print(f"    {k}: {v}")
        print(f"  Total combinations: {total_combos}")

        # Screen entire grid on subsampled data
        results = run_sweep(
            screen_data,
            "ADAPTIVE_MULTI (subsampled)",
            grid,
            n_workers=args.workers,
            subsample_factor=args.subsample,
        )
        if results and args.subsample > 1:
            top_n = min(10, len(results))
            validated = revalidate(full_data, results, top_n=top_n)
            if validated:
                print_results(
                    validated, "ADAPTIVE_MULTI (full data)", top_n=len(validated)
                )
                best_params_accumulator.update(validated[0]["params"])
                all_phase_results.extend(validated)
        else:
            best = print_results(results, "ADAPTIVE_MULTI")
            if best:
                best_params_accumulator.update(best["params"])

    # ---- PHASE 4: OOS VALIDATION ----
    if args.phase == "oos":
        oos_overrides = (
            json.loads(args.oos_params) if args.oos_params else DEFAULTS.copy()
        )
        print("\n" + "=" * 90)
        print("OUT-OF-SAMPLE VALIDATION")
        print("=" * 90)
        result = run_oos(full_data, oos_overrides)
        print_oos(result)

    elif args.phase == "all":
        print("\n" + "=" * 90)
        print("PHASE 4: OOS VALIDATION (best candidate)")
        print("=" * 90)
        print("  Params changed from defaults:")
        for k, v in sorted(best_params_accumulator.items()):
            if v != DEFAULTS.get(k):
                print(f"    {k}: {DEFAULTS.get(k)} -> {v}")
        oos_result = run_oos(full_data, best_params_accumulator)
        print_oos(oos_result)

    # ---- FINAL SUMMARY ----
    if all_phase_results:
        all_phase_results.sort(key=lambda x: x["_score"], reverse=True)
        print("\n" + "=" * 90)
        print("OVERALL TOP 10 (full-data validated)")
        print("=" * 90)
        header = (
            f"{'Return%':>10} {'DD%':>8} {'Ret/DD':>8} {'PF':>8} "
            f"{'WR%':>6} {'Trades':>7} {'Score':>8} Params"
        )
        print(header)
        print("-" * 90)
        for r in all_phase_results[:10]:
            params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
            print(
                f"{r['total_return_pct']:>+10.2f} {r['max_drawdown_pct']:>8.2f} "
                f"{r['total_return_pct'] / max(r['max_drawdown_pct'], 0.01):>8.2f} "
                f"{r['profit_factor']:>8.2f} "
                f"{r['win_rate_pct']:>5.1f}% {r['num_trades']:>7d} "
                f"{r['_score']:>8.2f} {params_str}"
            )
        print()

    reset_params()
    print("Done.")


if __name__ == "__main__":
    main()
