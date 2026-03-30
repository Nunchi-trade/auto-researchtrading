"""15m Strategy Parameter Tuning — comprehensive sweep over all 36 parameters.

Phases:
  1. Single-parameter sweeps (each param independently, subsampled)
  1b. Re-validate phase 1 winners on full data
  2. Secondary sweeps (paired params + lookback windows, subsampled)
  2b. Re-validate phase 2 winners on full data
  3. Adaptive multi-parameter grid (subsampled, then top-10 on full data)
  4. Walk-forward validation of best candidate (expanding window, 5 folds)
  5. Parameter stability test (perturb ±10%, check robustness)

Scoring (aligned with prepare.py research framework):
  score = annualized_sharpe * sqrt(min(trades/50, 1.0))
          - drawdown_penalty - turnover_penalty
  drawdown_penalty = max(0, max_DD_pct - 15.0) * 0.05
  turnover_penalty = raw_penalty * max(0, 1 - sharpe_ann/10)
  Hard cutoffs (return -999): <10 trades, DD>50%, equity<50%

  Sharpe annualization: per_bar_sharpe * sqrt(bars_per_year)
  For 15m bars: 4 bars/hr * 24 * 365 = 35040 bars/year
"""

import sys
import os
import time
import math
import itertools
import json
import argparse
import multiprocessing as mp
from pathlib import Path
import numpy as np
import pandas as pd

_this_dir = Path(__file__).resolve().parent
_pipeline_root = _this_dir.parent
_repo_root = _pipeline_root.parent
_live_bot_root = _repo_root / "live_trading_bot"
for _p in (_this_dir, _pipeline_root, _live_bot_root):
    sp = str(_p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
sys.path = [p for p in sys.path if Path(p).resolve() != _repo_root]
sys.path.append(str(_repo_root))

from backtest_interval import run_backtest_1m, load_data
import strategies.strategy_15m as s15m

BARS_PER_YEAR_15M = 4 * 24 * 365  # 35040

# ---------------------------------------------------------------------------
# DEFAULTS
# ---------------------------------------------------------------------------
from constants import STRATEGY_DEFAULTS

DEFAULTS = dict(STRATEGY_DEFAULTS["15m"])

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
# SCORING — aligned with prepare.py compute_score()
# ---------------------------------------------------------------------------
def annualize_sharpe(per_bar_sharpe: float, bars_processed: int) -> float:
    if per_bar_sharpe == 0 or bars_processed < 20:
        return 0.0
    return per_bar_sharpe * math.sqrt(BARS_PER_YEAR_15M)


def score_result(r: dict) -> float:
    num_trades = r.get("num_closes", r.get("num_trades", 0))
    max_dd = r.get("max_drawdown_pct", 0.0)
    final_equity = r.get("final_equity", 10000.0)

    if num_trades < 10:
        return -999.0
    if max_dd > 50.0:
        return -999.0
    if final_equity < 10000.0 * 0.5:
        return -999.0

    per_bar_sharpe = r.get("sharpe", 0.0)
    bars_processed = r.get("bars_processed", 0)
    sharpe_ann = annualize_sharpe(per_bar_sharpe, bars_processed)

    trade_count_factor = min(num_trades / 50.0, 1.0)
    dd_penalty = max(0, max_dd - 15.0) * 0.05

    annual_turnover = r.get("annual_turnover", 0.0)
    turnover_ratio = annual_turnover / 10000.0 if 10000.0 > 0 else 0
    raw_turnover_penalty = max(0, turnover_ratio - 500) * 0.001
    # Scale penalty by inverse Sharpe: high-Sharpe strategies (>=10) get free pass,
    # low-Sharpe strategies (<10) get progressively penalized for churning.
    # This prevents the tuner from sacrificing returns to cut turnover.
    turnover_penalty = raw_turnover_penalty * max(0.0, 1.0 - sharpe_ann / 10.0)

    score = sharpe_ann * math.sqrt(trade_count_factor) - dd_penalty - turnover_penalty
    return score


# ---------------------------------------------------------------------------
# RESULT PERSISTENCE — save/load tuning results for iterative improvement
# ---------------------------------------------------------------------------
_RESULTS_DIR = Path(__file__).resolve().parent.parent / "tuning_results"


def _to_native(obj):
    if isinstance(obj, (np.bool_, np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


def save_results(
    best_params: dict,
    best_score: float,
    all_phase_results: list[dict],
    walk_forward: dict | None,
    stability: dict | None,
    previous_file: str | None = None,
    per_symbol_best_params: dict[str, dict] | None = None,
    per_symbol_best_scores: dict[str, float] | None = None,
) -> str:
    """Save tuning results to JSON file. Returns the filename saved."""
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tune_15m_{ts}.json"
    filepath = _RESULTS_DIR / filename

    # Build serializable result
    entry = {
        "timestamp": ts,
        "previous_run": previous_file,
        "best_params": best_params,
        "best_score": best_score,
        "walk_forward_pass": bool(walk_forward["pass"]) if walk_forward else None,
        "walk_forward_avg_return": float(walk_forward["avg_test_return"])
        if walk_forward
        else None,
        "stability_pass": bool(stability["pass"]) if stability else None,
        "stability_max_drop_pct": float(stability["max_score_drop_pct"])
        if stability
        else None,
    }

    entry["format_version"] = 2
    if per_symbol_best_params:
        entry["per_symbol_best_params"] = _to_native(per_symbol_best_params)
    if per_symbol_best_scores:
        entry["per_symbol_best_scores"] = _to_native(per_symbol_best_scores)

    # Top 10 phase results (lightweight — just key metrics + params)
    top10 = sorted(all_phase_results, key=lambda x: x.get("_score", 0), reverse=True)[
        :10
    ]
    entry["top10_results"] = []
    for r in top10:
        sharpe_ann = annualize_sharpe(r.get("sharpe", 0), r.get("bars_processed", 0))
        entry["top10_results"].append(
            {
                "params": r.get("params", {}),
                "score": r.get("_score", 0),
                "return_pct": r.get("total_return_pct", 0),
                "dd_pct": r.get("max_drawdown_pct", 0),
                "sharpe_ann": sharpe_ann,
                "trades": r.get("num_trades", 0),
                "profit_factor": r.get("profit_factor", 0),
            }
        )

    # Atomic write (same pattern as sliding_window_tune.py)
    tmp_path = filepath.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(_to_native(entry), fh, indent=2)
            fh.write("\n")
        os.rename(tmp_path, filepath)
        print(f"  Results saved to: {filepath}")
        return filename
    except Exception as exc:
        print(f"  [WARN] Failed to write JSON: {exc}")
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return ""


def load_latest_results() -> tuple[dict | None, str | None, dict[str, dict] | None]:
    """Load the most recent tuning results file. Returns (best_params, filename, per_symbol_params)."""
    if not _RESULTS_DIR.exists():
        return None, None, None

    json_files = sorted(_RESULTS_DIR.glob("tune_15m_*.json"))
    if not json_files:
        return None, None, None

    latest = json_files[-1]
    print(f"  Loading previous results from: {latest.name}")
    try:
        with open(latest, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        best_params = data.get("best_params")
        prev_score = data.get("best_score", 0)
        wf_pass = data.get("walk_forward_pass")
        stab_pass = data.get("stability_pass")

        print(f"  Previous best score: {prev_score:.2f}")
        if wf_pass is not None:
            print(f"  Previous walk-forward: {'PASS' if wf_pass else 'FAIL'}")
        if stab_pass is not None:
            print(f"  Previous stability: {'PASS' if stab_pass else 'FAIL'}")

        # Show what changed from defaults
        if best_params:
            changes = {k: v for k, v in best_params.items() if v != DEFAULTS.get(k)}
            if changes:
                print(f"  Previous param changes: {changes}")

        per_symbol = data.get("per_symbol_best_params")
        return best_params, latest.name, per_symbol
    except Exception as exc:
        print(f"  [WARN] Failed to load {latest.name}: {exc}")
        return None, None, None


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
        {"BASE_POSITION_PCT": [0.04, 0.08, 0.15, 0.30, 0.60, 1.0, 1.5, 2.0]},
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
    ("MED2_WINDOW", {"MED2_WINDOW": [48, 72, 96, 120, 144]}),
    ("LONG_WINDOW", {"LONG_WINDOW": [96, 120, 144, 192, 240]}),
    ("ATR_LOOKBACK", {"ATR_LOOKBACK": [48, 72, 96, 120, 144]}),
    ("TARGET_VOL", {"TARGET_VOL": [0.005, 0.010, 0.015, 0.020, 0.030]}),
]


# ---------------------------------------------------------------------------
# PARAMETER MANAGEMENT
# ---------------------------------------------------------------------------
def reset_params(clear_symbol_params: bool = True):
    if clear_symbol_params:
        s15m._SYMBOL_PARAMS = {}
    for k, v in DEFAULTS.items():
        setattr(s15m, k, v)


def set_params(
    overrides: dict, subsample_factor: int = 1, clear_symbol_params: bool = True
):
    if clear_symbol_params:
        s15m._SYMBOL_PARAMS = {}
    for k, v in DEFAULTS.items():
        if subsample_factor > 1 and k in BAR_COUNT_PARAMS:
            setattr(s15m, k, max(1, int(round(v / subsample_factor))))
        else:
            setattr(s15m, k, v)
    for k, v in overrides.items():
        if subsample_factor > 1 and k in BAR_COUNT_PARAMS:
            v = max(1, int(round(v / subsample_factor)))
        if k in INT_PARAMS:
            v = int(v)
        setattr(s15m, k, v)


def set_params_per_symbol(per_symbol_params: dict[str, dict]):
    """Set per-symbol params for joint backtest (walk-forward, stability).

    Sets _SYMBOL_PARAMS to the provided per-symbol dict, resets module-level
    attrs to DEFAULTS as fallback values.
    """
    s15m._SYMBOL_PARAMS = {s: dict(p) for s, p in per_symbol_params.items()}
    for k, v in DEFAULTS.items():
        setattr(s15m, k, v)


def run_once(
    data,
    overrides: dict,
    subsample_factor: int = 1,
    preserve_symbol_params: bool = False,
) -> dict:
    set_params(
        overrides,
        subsample_factor=subsample_factor,
        clear_symbol_params=not preserve_symbol_params,
    )
    strategy = s15m.Strategy()
    result = run_backtest_1m(strategy, data, "15m")
    if "error" in result:
        return result
    result["params"] = dict(overrides)
    result["_score"] = score_result(result)
    return result


def _sweep_worker(args: tuple) -> dict:
    """Standalone worker: receives data explicitly, no globals.

    Args:
        args: (data, overrides, subsample_factor) tuple
    Returns:
        Scored result dict with params and _score
    """
    data, overrides, subsample_factor = args
    set_params(overrides, subsample_factor=subsample_factor)
    strategy = s15m.Strategy()
    result = run_backtest_1m(strategy, data, "15m")
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
        from concurrent.futures import ProcessPoolExecutor, as_completed

        ctx = mp.get_context("spawn")
        tasks = [(data, overrides, subsample_factor) for overrides in combos]
        timed_out = False
        try:
            with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as executor:
                futures = {
                    executor.submit(_sweep_worker, t): i for i, t in enumerate(tasks)
                }
                timeout = max(300, total * 10)
                raw = []
                try:
                    for future in as_completed(futures, timeout=timeout):
                        try:
                            raw.append(future.result(timeout=300))
                        except Exception:
                            pass
                except TimeoutError:
                    print(
                        f"\n  [POOL TIMEOUT] after {timeout}s, falling back to sequential"
                    )
                    timed_out = True
            if timed_out:
                raw = []
                for overrides in combos:
                    try:
                        r = run_once(data, overrides, subsample_factor=subsample_factor)
                        if "error" not in r:
                            raw.append(r)
                    except Exception:
                        pass
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


def _symbol_sweep_worker(args: tuple) -> list[dict]:
    symbol, parquet_path, combos, subsample_factor = args
    df = pd.read_parquet(parquet_path)
    if subsample_factor > 1:
        df = df.iloc[::subsample_factor].reset_index(drop=True)
    symbol_data = {symbol: df}

    results = []
    for overrides in combos:
        set_params(overrides, subsample_factor=1)
        strategy = s15m.Strategy()
        result = run_backtest_1m(strategy, symbol_data, "15m")
        result["params"] = dict(overrides)
        result["_symbol"] = symbol
        if "error" in result:
            result["_score"] = -1.0
        else:
            result["_score"] = score_result(result)
            results.append(result)
    return results


def run_sweep_per_symbol(
    all_data: dict,
    name: str,
    param_grid,
    n_workers: int = 4,
    subsample_factor: int = 1,
    data_dir: str | None = None,
) -> dict[str, list[dict]]:
    """Run parameter sweep independently per symbol using parallel workers.

    Each worker is assigned one symbol and runs ALL parameter combos
    sequentially for that symbol. Workers run in parallel across symbols.
    """
    if isinstance(param_grid, list):
        combos = [dict(p) for p in param_grid]
    else:
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combos = [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    total_per_symbol = len(combos)
    symbols = list(all_data.keys())
    n_workers = min(n_workers, len(symbols))
    print(
        f"  Per-symbol sweep '{name}': {total_per_symbol} combos x {len(symbols)} symbols ({n_workers} workers)..."
    )

    if data_dir is None:
        data_dir = str(_pipeline_root / "backtest_data" / "15m_candles")

    t0 = time.time()
    results: dict[str, list[dict]] = {}

    if n_workers > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        ctx = mp.get_context("spawn")

        tasks = []
        for symbol in symbols:
            parquet_path = os.path.join(data_dir, f"{symbol}_15m.parquet")
            tasks.append((symbol, parquet_path, combos, subsample_factor))

        try:
            with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as executor:
                futures = {
                    executor.submit(_symbol_sweep_worker, task): task[0]
                    for task in tasks
                }
                for future in as_completed(
                    futures, timeout=max(600, total_per_symbol * 15)
                ):
                    sym = futures[future]
                    try:
                        symbol_results = future.result(timeout=300)
                        results[sym] = [
                            r for r in symbol_results if r.get("_score", -1) >= 0
                        ]
                        print(
                            f"    {sym}: {len(results[sym])}/{total_per_symbol} valid results"
                        )
                    except Exception as e:
                        print(f"    {sym}: ERROR - {e}")
                        results[sym] = []
        except Exception as e:
            print(f"  [POOL ERROR] {e}, falling back to sequential")
            for symbol in symbols:
                symbol_data = {symbol: all_data[symbol]}
                symbol_results = []
                for overrides in combos:
                    try:
                        r = run_once(
                            symbol_data, overrides, subsample_factor=subsample_factor
                        )
                        if "error" not in r:
                            r["_symbol"] = symbol
                            symbol_results.append(r)
                    except Exception:
                        pass
                results[symbol] = symbol_results
    else:
        for symbol in symbols:
            symbol_data = {symbol: all_data[symbol]}
            symbol_results = []
            for i, overrides in enumerate(combos):
                try:
                    r = run_once(
                        symbol_data, overrides, subsample_factor=subsample_factor
                    )
                    if "error" not in r:
                        r["_symbol"] = symbol
                        symbol_results.append(r)
                except Exception as e:
                    print(f"  [ERROR] {overrides}: {e}")
                elapsed = time.time() - t0
                eta = elapsed / (i + 1) * (total_per_symbol - i - 1) if i > 0 else 0
                print(
                    f"\r  [{symbol}] {(i + 1) / total_per_symbol * 100:5.1f}% "
                    f"({i + 1}/{total_per_symbol})  ETA: {eta:.0f}s   ",
                    end="",
                    flush=True,
                )
            results[symbol] = symbol_results
            print()

    elapsed = time.time() - t0
    total_valid = sum(len(v) for v in results.values())
    print(
        f"  Completed per-symbol sweep in {elapsed:.1f}s ({total_valid} valid results across {len(symbols)} symbols)"
    )
    return results


# ---------------------------------------------------------------------------
# RESULTS PRINTING
# ---------------------------------------------------------------------------
def print_results(results: list[dict], name: str, top_n: int = 5):
    if not results:
        print(f"  No valid results for {name}")
        return None

    results.sort(key=lambda x: x["_score"], reverse=True)

    print(f"\n{'=' * 110}")
    print(f"SWEEP: {name}")
    print(f"{'=' * 110}")
    header = (
        f"{'Return%':>10} {'DD%':>8} {'Sharpe':>8} {'PF':>8} "
        f"{'WR%':>6} {'Trades':>7} {'Turnover':>10} {'Score':>8} Params"
    )
    print(header)
    print("-" * 110)
    for r in results[:top_n]:
        params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
        sharpe_ann = annualize_sharpe(r.get("sharpe", 0), r.get("bars_processed", 0))
        turnover = r.get("annual_turnover", 0)
        print(
            f"{r['total_return_pct']:>+10.2f} {r['max_drawdown_pct']:>8.2f} "
            f"{sharpe_ann:>8.2f} "
            f"{r['profit_factor']:>8.2f} "
            f"{r['win_rate_pct']:>5.1f}% {r['num_trades']:>7d} "
            f"${turnover:>9,.0f} "
            f"{r['_score']:>8.2f} {params_str}"
        )
    if len(results) > top_n:
        print(f"  ... ({len(results) - top_n} more)")
    best = results[0]
    best_params = ", ".join(f"{k}={v}" for k, v in best["params"].items())
    sharpe_ann = annualize_sharpe(best.get("sharpe", 0), best.get("bars_processed", 0))
    print(
        f"\nBEST: {best_params} "
        f"-> Score={best['_score']:.2f}, Sharpe={sharpe_ann:.2f}, "
        f"DD={best['max_drawdown_pct']:.2f}%, "
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


def revalidate_per_symbol(
    full_data: dict,
    per_symbol_results: dict[str, list[dict]],
    top_n: int = 2,
) -> dict[str, list[dict]]:
    validated: dict[str, list[dict]] = {}
    for symbol, results in per_symbol_results.items():
        if results:
            symbol_data = {symbol: full_data[symbol]}
            validated[symbol] = revalidate(symbol_data, results, top_n=top_n)
        else:
            validated[symbol] = []
    return validated


def forward_stepwise_per_symbol(
    full_data: dict,
    per_symbol_results: dict[str, list[dict]],
    initial_params: dict | None = None,
) -> dict[str, tuple[dict, float]]:
    """Run forward stepwise accumulation independently for each symbol."""
    per_symbol_best: dict[str, tuple[dict, float]] = {}
    for symbol, phase_results in per_symbol_results.items():
        if not phase_results:
            per_symbol_best[symbol] = (initial_params or DEFAULTS.copy(), 0.0)
            continue
        symbol_data = {symbol: full_data[symbol]}
        params, score = forward_stepwise_accumulate(
            symbol_data, phase_results, initial_params=initial_params
        )
        per_symbol_best[symbol] = (params, score)
        print(f"  {symbol} stepwise score: {score:.2f}")
    return per_symbol_best


# Params to include in adaptive grid, with value generators
ADAPTIVE_GRID_PARAMS = {
    "RSI_PERIOD": lambda v: sorted(
        set([max(8, v - 8), max(8, v - 4), v, v + 4, v + 8])
    ),
    "BASE_POSITION_PCT": lambda v: sorted(
        set(
            [
                round(max(0.02, min(2.0, v * 0.25)), 3),
                round(max(0.02, min(2.0, v * 0.5)), 3),
                round(min(2.0, v), 3),
                round(min(2.0, v * 2), 3),
                round(min(2.0, v * 4), 3),
            ]
        )
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
    Caps total combinations at 36 to prevent timeout.
    """
    grid = {}

    changes = {k: v for k, v in best_params.items() if v != DEFAULTS.get(k)}

    # Prioritize params: RSI_PERIOD first, then changed params
    ordered_params = []
    for param in ADAPTIVE_GRID_PARAMS:
        if param == "RSI_PERIOD":
            ordered_params.insert(0, param)
        elif param in changes:
            ordered_params.append(param)

    for param in ordered_params:
        val = best_params.get(param, DEFAULTS[param])
        if param in INT_PARAMS:
            val = int(val)
        grid[param] = ADAPTIVE_GRID_PARAMS[param](val)

        # Check total combos — cap at 36
        total = 1
        for v in grid.values():
            total *= len(v)
        if total > 36:
            excess = total // len(grid[param])
            max_vals = 36 // excess
            if max_vals < 2:
                del grid[param]
                break
            vals = grid[param]
            if len(vals) > max_vals:
                indices = [
                    int(i * (len(vals) - 1) / (max_vals - 1)) for i in range(max_vals)
                ]
                grid[param] = sorted(set(vals[i] for i in indices))

    if not grid:
        grid["RSI_PERIOD"] = [24, 28, 32, 40]

    return grid


def build_adaptive_grid_per_symbol(
    per_symbol_best: dict[str, tuple[dict, float]],
) -> dict[str, dict]:
    per_symbol_grid: dict[str, dict] = {}
    for symbol, (best_params, score) in per_symbol_best.items():
        per_symbol_grid[symbol] = build_adaptive_grid(best_params)
    return per_symbol_grid


# ---------------------------------------------------------------------------
# WALK-FORWARD VALIDATION
# ---------------------------------------------------------------------------
def run_walk_forward(
    data, overrides: dict, n_folds: int = 5, preserve_symbol_params: bool = False
) -> dict:
    all_ts = set()
    for df in data.values():
        all_ts.update(df["timestamp"].tolist())
    timestamps = sorted(all_ts)
    total_bars = len(timestamps)

    fold_results = []
    for fold in range(n_folds):
        train_end_pct = 0.3 + (fold + 1) * (0.7 / n_folds)
        train_end_idx = int(total_bars * train_end_pct)
        if train_end_idx >= total_bars - 100:
            break

        split_ts = timestamps[train_end_idx]

        train_data, test_data = {}, {}
        for symbol, df in data.items():
            t_df = df[df["timestamp"] <= split_ts].copy()
            o_df = df[df["timestamp"] > split_ts].copy()
            if len(t_df) > 0:
                train_data[symbol] = t_df
            if len(o_df) > 0:
                test_data[symbol] = o_df

        train_bars = sum(len(df) for df in train_data.values())
        test_bars = sum(len(df) for df in test_data.values())

        set_params(overrides, clear_symbol_params=not preserve_symbol_params)
        train_result = run_backtest_1m(s15m.Strategy(), train_data, "15m")
        set_params(overrides, clear_symbol_params=not preserve_symbol_params)
        test_result = run_backtest_1m(s15m.Strategy(), test_data, "15m")

        train_result["final_equity"] = train_result.get("final_equity", 10000.0)
        test_result["final_equity"] = test_result.get("final_equity", 10000.0)

        train_score = score_result(train_result)
        test_score = score_result(test_result)

        fold_results.append(
            {
                "fold": fold + 1,
                "train_pct": train_end_pct,
                "train_bars": train_bars,
                "test_bars": test_bars,
                "train_return": train_result.get("total_return_pct", 0),
                "train_dd": train_result.get("max_drawdown_pct", 0),
                "train_sharpe": annualize_sharpe(
                    train_result.get("sharpe", 0), train_result.get("bars_processed", 0)
                ),
                "train_score": train_score,
                "test_return": test_result.get("total_return_pct", 0),
                "test_dd": test_result.get("max_drawdown_pct", 0),
                "test_sharpe": annualize_sharpe(
                    test_result.get("sharpe", 0), test_result.get("bars_processed", 0)
                ),
                "test_score": test_score,
                "degradation": (train_score - test_score) / train_score
                if train_score > 0
                else float("inf"),
            }
        )

    if not fold_results:
        return {"error": "insufficient data for walk-forward", "fold_results": []}

    avg_test_score = np.mean([f["test_score"] for f in fold_results])
    avg_test_return = np.mean([f["test_return"] for f in fold_results])
    avg_test_dd = np.mean([f["test_dd"] for f in fold_results])
    avg_degradation = np.mean(
        [f["degradation"] for f in fold_results if f["degradation"] != float("inf")]
    )
    worst_degradation = max(
        f["degradation"] for f in fold_results if f["degradation"] != float("inf")
    )
    positive_folds = sum(1 for f in fold_results if f["test_return"] > 0)
    consistent = positive_folds / len(fold_results) >= 0.6

    return {
        "params": dict(overrides),
        "n_folds": len(fold_results),
        "fold_results": fold_results,
        "avg_test_score": avg_test_score,
        "avg_test_return": avg_test_return,
        "avg_test_dd": avg_test_dd,
        "avg_degradation": avg_degradation,
        "worst_degradation": worst_degradation,
        "consistent": consistent,
        "pass": consistent and avg_degradation < 0.5 and avg_test_return > 0,
    }


# ---------------------------------------------------------------------------
# PARAMETER STABILITY TEST
# ---------------------------------------------------------------------------
def test_stability(
    data,
    overrides: dict,
    perturbation: float = 0.1,
    preserve_symbol_params: bool = False,
) -> dict:
    baseline = run_once(data, overrides)
    if "error" in baseline:
        return {"stable": False, "reason": "baseline error", "details": []}

    baseline_score = baseline["_score"]
    perturbable = [
        k
        for k, v in overrides.items()
        if isinstance(v, (int, float)) and k not in ("MIN_VOTES",)
    ]

    details = []
    max_score_drop = 0.0
    for k in perturbable:
        val = overrides[k]
        for direction, factor in [("+", 1 + perturbation), ("-", 1 - perturbation)]:
            if k in INT_PARAMS:
                perturbed_val = max(1, int(round(val * factor)))
                if perturbed_val == val:
                    perturbed_val += 1 if factor > 1 else -1
                    perturbed_val = max(1, perturbed_val)
            else:
                perturbed_val = round(max(0.001, val * factor), 6)

            test_overrides = dict(overrides)
            test_overrides[k] = perturbed_val
            test_result = run_once(
                data, test_overrides, preserve_symbol_params=preserve_symbol_params
            )
            if "error" in test_result:
                continue
            test_score = test_result["_score"]
            drop = (baseline_score - test_score) / max(abs(baseline_score), 0.01)
            max_score_drop = max(max_score_drop, drop)
            details.append(
                {
                    "param": k,
                    "direction": direction,
                    "original": val,
                    "perturbed": perturbed_val,
                    "score": test_score,
                    "drop_pct": drop * 100,
                }
            )

    stable = max_score_drop < 0.3
    return {
        "stable": stable,
        "baseline_score": baseline_score,
        "max_score_drop_pct": max_score_drop * 100,
        "n_params_tested": len(perturbable),
        "details": sorted(details, key=lambda x: -x["drop_pct"]),
        "pass": stable,
    }


def print_walk_forward(wf: dict):
    print(f"\n{'=' * 90}")
    print("WALK-FORWARD VALIDATION")
    print(f"{'=' * 90}")
    params_str = ", ".join(f"{k}={v}" for k, v in wf["params"].items())
    print(f"Params: {params_str}")
    print(f"Folds: {wf['n_folds']}")
    print()
    print(
        f"{'Fold':>6} {'Train%':>8} {'TrBars':>8} {'TeBars':>8} "
        f"{'TrRet%':>9} {'TeRet%':>9} {'TrDD%':>8} {'TeDD%':>8} "
        f"{'TrScore':>9} {'TeScore':>9} {'Degrad%':>9}"
    )
    print("-" * 110)
    for f in wf["fold_results"]:
        deg = f["degradation"]
        deg_str = f"{deg * 100:.1f}%" if deg != float("inf") else "INF"
        print(
            f"{f['fold']:>6} {f['train_pct']:>8.0%} {f['train_bars']:>8} {f['test_bars']:>8} "
            f"{f['train_return']:>+9.2f} {f['test_return']:>+9.2f} "
            f"{f['train_dd']:>8.2f} {f['test_dd']:>8.2f} "
            f"{f['train_score']:>9.2f} {f['test_score']:>9.2f} {deg_str:>9}"
        )
    print("-" * 110)
    print(
        f"{'AVG':>6} {'':>8} {'':>8} {'':>8} "
        f"{'':>9} {wf['avg_test_return']:>+9.2f} {'':>8} {wf['avg_test_dd']:>8.2f} "
        f"{'':>9} {wf['avg_test_score']:>9.2f} {wf['avg_degradation'] * 100:>8.1f}%"
    )
    verdict = "PASS" if wf["pass"] else "FAIL"
    print(
        f"\n  Consistent (>60% positive folds): {wf['consistent']}  |  Verdict: {verdict}"
    )


def print_stability(stab: dict):
    print(f"\n{'=' * 90}")
    print("PARAMETER STABILITY TEST")
    print(f"{'=' * 90}")
    print(f"  Baseline score:  {stab['baseline_score']:.2f}")
    print(f"  Max score drop:  {stab['max_score_drop_pct']:.1f}%")
    print(f"  Params tested:   {stab['n_params_tested']}")
    print(
        f"  Verdict:         {'STABLE' if stab['stable'] else 'UNSTABLE — results likely fragile'}"
    )
    if stab["details"]:
        print(
            f"\n  {'Param':>25} {'Dir':>4} {'Orig':>10} {'Perturb':>10} {'Score':>9} {'Drop%':>8}"
        )
        print("  " + "-" * 70)
        for d in stab["details"][:15]:
            print(
                f"  {d['param']:>25} {d['direction']:>4} {d['original']:>10} "
                f"{d['perturbed']:>10} {d['score']:>9.2f} {d['drop_pct']:>7.1f}%"
            )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="15m Strategy Parameter Tuning")
    parser.add_argument(
        "--phase",
        choices=["single", "secondary", "multi", "validate", "all"],
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
    parser.add_argument(
        "--load-previous",
        action="store_true",
        default=False,
        help="Load best params from latest tuning_results/ JSON as starting point",
    )
    args = parser.parse_args()

    full_data = load_data(
        interval="15m", data_dir=str(_pipeline_root / "backtest_data" / "15m_candles")
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
    per_symbol_best_accumulator: dict[str, tuple[dict, float]] | None = None

    previous_file = None
    if args.load_previous:
        prev_params, previous_file, prev_per_symbol = load_latest_results()
        if prev_per_symbol:
            per_symbol_best_accumulator = {
                s: (p, 0.0) for s, p in prev_per_symbol.items()
            }
        if prev_params:
            best_params_accumulator = prev_params.copy()
            for k, v in DEFAULTS.items():
                if k not in best_params_accumulator:
                    best_params_accumulator[k] = v
            print(f"  Starting from previous best params (score from file)")
        else:
            print("  No previous results found, starting from defaults")

    # ---- PHASE 1: SINGLE-PARAMETER SWEEPS (screen on subsampled, per-symbol) ----
    per_symbol_phase_results: dict[str, list[dict]] = {}
    if args.phase in ("single", "all"):
        print("\n" + "=" * 90)
        print("PHASE 1: SINGLE-PARAMETER SWEEPS (per-symbol, subsampled)")
        print("=" * 90)
        for name, grid in SINGLE_SWEEPS:
            per_symbol_results = run_sweep_per_symbol(
                screen_data,
                name,
                grid,
                n_workers=args.workers,
                subsample_factor=args.subsample,
            )
            if args.subsample > 1:
                per_symbol_results = revalidate_per_symbol(
                    full_data, per_symbol_results, top_n=args.revalidate_top
                )
            for symbol, results in per_symbol_results.items():
                if symbol not in per_symbol_phase_results:
                    per_symbol_phase_results[symbol] = []
                per_symbol_phase_results[symbol].extend(results)
                if results:
                    best_screen = print_results(results, f"{name} [{symbol}]")
                    all_phase_results.extend(results)
                    best_r = results[0]
                    if (
                        best_overall_result is None
                        or best_r["_score"] > best_overall_result["_score"]
                    ):
                        best_overall_result = best_r

    # ---- PHASE 2: SECONDARY SWEEPS (screen on subsampled, per-symbol) ----
    if args.phase in ("secondary", "all"):
        print("\n" + "=" * 90)
        print("PHASE 2: SECONDARY SWEEPS (per-symbol, subsampled)")
        print("=" * 90)
        for name, grid in SECONDARY_SWEEPS:
            per_symbol_results = run_sweep_per_symbol(
                screen_data,
                name,
                grid,
                n_workers=args.workers,
                subsample_factor=args.subsample,
            )
            if args.subsample > 1:
                per_symbol_results = revalidate_per_symbol(
                    full_data, per_symbol_results, top_n=args.revalidate_top
                )
            for symbol, results in per_symbol_results.items():
                if symbol not in per_symbol_phase_results:
                    per_symbol_phase_results[symbol] = []
                per_symbol_phase_results[symbol].extend(results)
                if results:
                    best_screen = print_results(results, f"{name} [{symbol}]")
                    all_phase_results.extend(results)
                    best_r = results[0]
                    if (
                        best_overall_result is None
                        or best_r["_score"] > best_overall_result["_score"]
                    ):
                        best_overall_result = best_r

    # ---- FORWARD STEPWISE ACCUMULATOR (per-symbol) ----
    stepwise_score = 0.0
    if per_symbol_phase_results and args.phase in ("secondary", "multi", "all"):
        print("\n" + "=" * 90)
        print("FORWARD STEPWISE ACCUMULATOR (per-symbol)")
        print("=" * 90)
        per_symbol_best_accumulator = forward_stepwise_per_symbol(
            full_data, per_symbol_phase_results, initial_params=best_params_accumulator
        )
        for symbol, (params, score) in per_symbol_best_accumulator.items():
            changes = {k: v for k, v in params.items() if v != DEFAULTS.get(k)}
            print(f"  {symbol} stepwise changes: {changes}, score: {score:.2f}")
        per_symbol_params = {
            s: params for s, (params, score) in per_symbol_best_accumulator.items()
        }
        set_params_per_symbol(per_symbol_params)
        joint_result = run_once(full_data, DEFAULTS.copy(), preserve_symbol_params=True)
        if "error" not in joint_result:
            stepwise_score = joint_result["_score"]
            print(
                f"  Joint portfolio score with per-symbol params: {stepwise_score:.2f}"
            )
            if (
                best_overall_result is None
                or stepwise_score > best_overall_result["_score"]
            ):
                joint_result["params"] = best_params_accumulator.copy()
                best_overall_result = joint_result
    elif best_overall_result is not None and args.phase in (
        "secondary",
        "multi",
        "all",
    ):
        print("\n" + "=" * 90)
        print("FORWARD STEPWISE ACCUMULATOR")
        print("=" * 90)
        stepwise_params, stepwise_score = forward_stepwise_accumulate(
            full_data, all_phase_results, initial_params=best_params_accumulator
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

    # ---- PHASE 3: ADAPTIVE MULTI-PARAMETER GRID (per-symbol) ----
    if args.phase in ("multi", "all"):
        if per_symbol_best_accumulator:
            per_symbol_grid = build_adaptive_grid_per_symbol(
                per_symbol_best_accumulator
            )
            print("\n" + "=" * 90)
            print("PHASE 3: ADAPTIVE MULTI-PARAMETER GRID (per-symbol)")
            print("=" * 90)
            for symbol, grid in per_symbol_grid.items():
                total_combos = 1
                for v in grid.values():
                    total_combos *= len(v)
                print(f"  {symbol} adaptive grid: {total_combos} combinations")

                symbol_screen = {symbol: screen_data[symbol]}
                results = run_sweep(
                    symbol_screen,
                    f"ADAPTIVE [{symbol}]",
                    grid,
                    n_workers=min(args.workers, total_combos),
                    subsample_factor=args.subsample,
                )
                best_screen = print_results(results, f"ADAPTIVE [{symbol}]")
                if results and args.subsample > 1:
                    symbol_full = {symbol: full_data[symbol]}
                    validated = revalidate(
                        symbol_full, results, top_n=min(10, len(results))
                    )
                    if validated:
                        print_results(
                            validated,
                            f"ADAPTIVE [{symbol}] (full)",
                            top_n=len(validated),
                        )
                        current_params, _ = per_symbol_best_accumulator.get(
                            symbol, (DEFAULTS.copy(), 0.0)
                        )
                        current_params = current_params.copy()
                        current_params.update(validated[0]["params"])
                        per_symbol_best_accumulator[symbol] = (
                            current_params,
                            validated[0]["_score"],
                        )
                        all_phase_results.extend(validated)
                        if (
                            best_overall_result is None
                            or validated[0]["_score"] > best_overall_result["_score"]
                        ):
                            best_overall_result = validated[0]
                elif best_screen:
                    all_phase_results.append(best_screen)
                    if (
                        best_overall_result is None
                        or best_screen["_score"] > best_overall_result["_score"]
                    ):
                        best_overall_result = best_screen
        else:
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

    # ---- PHASE 4: WALK-FORWARD VALIDATION ----
    wf_result = None
    stab_result = None
    if args.phase == "validate":
        validate_overrides = (
            json.loads(args.oos_params) if args.oos_params else DEFAULTS.copy()
        )
        print("\n" + "=" * 90)
        print("WALK-FORWARD VALIDATION")
        print("=" * 90)
        wf = run_walk_forward(full_data, validate_overrides)
        if "error" not in wf:
            print_walk_forward(wf)
            wf_result = wf
            stab = test_stability(full_data, validate_overrides)
            print_stability(stab)
            stab_result = stab

    elif args.phase == "all":
        print("\n" + "=" * 90)
        print("PHASE 4: WALK-FORWARD VALIDATION (best candidate)")
        print("=" * 90)
        if per_symbol_best_accumulator:
            per_symbol_params = {
                s: params for s, (params, score) in per_symbol_best_accumulator.items()
            }
            set_params_per_symbol(per_symbol_params)
            print("  Using per-symbol params for joint walk-forward:")
            for symbol, params in per_symbol_params.items():
                changes = {k: v for k, v in params.items() if v != DEFAULTS.get(k)}
                print(f"    {symbol}: {changes}")
            wf = run_walk_forward(
                full_data, best_params_accumulator, preserve_symbol_params=True
            )
        else:
            print("  Params changed from defaults:")
            for k, v in sorted(best_params_accumulator.items()):
                if v != DEFAULTS.get(k):
                    print(f"    {k}: {DEFAULTS.get(k)} -> {v}")
            wf = run_walk_forward(full_data, best_params_accumulator)
        if "error" not in wf:
            print_walk_forward(wf)
            wf_result = wf

        print("\n" + "=" * 90)
        print("PHASE 5: PARAMETER STABILITY TEST")
        print("=" * 90)
        if per_symbol_best_accumulator:
            ps_for_stab = {
                s: params for s, (params, score) in per_symbol_best_accumulator.items()
            }
            set_params_per_symbol(ps_for_stab)
            stab = test_stability(
                full_data, best_params_accumulator, preserve_symbol_params=True
            )
        else:
            stab = test_stability(full_data, best_params_accumulator)
        print_stability(stab)
        stab_result = stab

    # ---- FINAL SUMMARY ----
    if all_phase_results:
        all_phase_results.sort(key=lambda x: x["_score"], reverse=True)
        print("\n" + "=" * 110)
        print("OVERALL TOP 10 (full-data validated)")
        print("=" * 110)
        header = (
            f"{'Return%':>10} {'DD%':>8} {'Sharpe':>8} {'PF':>8} "
            f"{'WR%':>6} {'Trades':>7} {'Turnover':>10} {'Score':>8} Params"
        )
        print(header)
        print("-" * 110)
        for r in all_phase_results[:10]:
            params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
            sharpe_ann = annualize_sharpe(
                r.get("sharpe", 0), r.get("bars_processed", 0)
            )
            turnover = r.get("annual_turnover", 0)
            print(
                f"{r['total_return_pct']:>+10.2f} {r['max_drawdown_pct']:>8.2f} "
                f"{sharpe_ann:>8.2f} "
                f"{r['profit_factor']:>8.2f} "
                f"{r['win_rate_pct']:>5.1f}% {r['num_trades']:>7d} "
                f"${turnover:>9,.0f} "
                f"{r['_score']:>8.2f} {params_str}"
            )
        print()

    # ---- SAVE RESULTS ----
    if best_overall_result is not None:
        accumulator_is_default = not any(
            best_params_accumulator.get(k) != DEFAULTS.get(k)
            for k in best_overall_result.get("params", {})
        )
        if accumulator_is_default:
            save_params = DEFAULTS.copy()
            save_params.update(best_overall_result["params"])
        else:
            save_params = best_params_accumulator

        per_symbol_save_params = None
        per_symbol_save_scores = None
        if per_symbol_best_accumulator:
            per_symbol_save_params = {
                s: params for s, (params, score) in per_symbol_best_accumulator.items()
            }
            per_symbol_save_scores = {
                s: score for s, (params, score) in per_symbol_best_accumulator.items()
            }

        save_results(
            save_params,
            best_overall_result.get("_score", 0),
            all_phase_results,
            wf_result,
            stab_result,
            previous_file=previous_file,
            per_symbol_best_params=per_symbol_save_params,
            per_symbol_best_scores=per_symbol_save_scores,
        )

    reset_params()
    print("Done.")


if __name__ == "__main__":
    main()
