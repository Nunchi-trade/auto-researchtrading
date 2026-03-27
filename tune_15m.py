import sys
import time
import itertools
import json
import argparse
import numpy as np
import pandas as pd

from backtest_interval import run_backtest_1m, load_data
import strategies.strategy_15m as s15m

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
    "BASE_POSITION_PCT": 2.00,
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
}

SINGLE_SWEEPS = [
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
]

MULTI_GRID = {
    "ATR_STOP_MULT": [4.0, 5.0, 5.5, 6.0],
    "COOLDOWN_BARS": [4, 8, 12],
    "MIN_VOTES": [3, 4, 5],
}


def reset_params():
    for k, v in DEFAULTS.items():
        setattr(s15m, k, v)


def set_params(overrides: dict):
    reset_params()
    for k, v in overrides.items():
        if k in INT_PARAMS:
            v = int(v)
        setattr(s15m, k, v)


def run_once(data, overrides: dict) -> dict:
    set_params(overrides)
    strategy = s15m.Strategy()
    result = run_backtest_1m(strategy, data, "15m")
    if "error" in result:
        return result
    result["params"] = dict(overrides)
    return result


def run_sweep(data, name: str, param_grid) -> list[dict]:
    if isinstance(param_grid, list):
        combos = [dict(p) for p in param_grid]
    else:
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combos = [dict(zip(keys, combo)) for combo in itertools.product(*values)]
    results = []
    total = len(combos)
    print(f"  Running {total} combinations...")
    for i, overrides in enumerate(combos):
        try:
            r = run_once(data, overrides)
            if "error" not in r:
                results.append(r)
            else:
                print(f"  [SKIP] {overrides}: {r['error']}")
        except Exception as e:
            print(f"  [ERROR] {overrides}: {e}")
        pct = (i + 1) / total * 100
        print(f"\r  Progress: {pct:5.1f}%", end="", flush=True)
    print()
    return results


def print_results(results: list[dict], name: str):
    if not results:
        print(f"  No valid results for {name}")
        return
    for r in results:
        dd = r["max_drawdown_pct"]
        ret_dd = r["total_return_pct"] / max(dd, 0.01)
        r["_ret_dd"] = ret_dd
    results.sort(key=lambda x: x["_ret_dd"], reverse=True)

    print(f"\n{'=' * 70}")
    print(f"SWEEP: {name}")
    print(f"{'=' * 70}")
    header = f"{'Return%':>10} {'DD%':>8} {'Ret/DD':>8} {'PF':>8} {'WR%':>6} {'Trades':>7} Params"
    print(header)
    print("-" * 70)
    for r in results:
        params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
        print(
            f"{r['total_return_pct']:>+10.2f} {r['max_drawdown_pct']:>8.2f} "
            f"{r['_ret_dd']:>8.2f} {r['profit_factor']:>8.2f} "
            f"{r['win_rate_pct']:>5.1f}% {r['num_trades']:>7d} {params_str}"
        )
    best = results[0]
    best_params = ", ".join(f"{k}={v}" for k, v in best["params"].items())
    print(
        f"\nBEST: {best_params} -> Ret/DD={best['_ret_dd']:.2f}, PF={best['profit_factor']:.2f}, WR={best['win_rate_pct']:.1f}%"
    )
    print()


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

    return {
        "params": dict(overrides),
        "IS_return": is_result.get("total_return_pct", 0),
        "IS_dd": is_result.get("max_drawdown_pct", 0),
        "IS_pf": is_result.get("profit_factor", 0),
        "IS_wr": is_result.get("win_rate_pct", 0),
        "IS_trades": is_result.get("num_trades", 0),
        "OOS_return": oos_result.get("total_return_pct", 0),
        "OOS_dd": oos_result.get("max_drawdown_pct", 0),
        "OOS_pf": oos_result.get("profit_factor", 0),
        "OOS_wr": oos_result.get("win_rate_pct", 0),
        "OOS_trades": oos_result.get("num_trades", 0),
    }


def print_oos(result: dict):
    print(f"\n{'=' * 70}")
    print("OUT-OF-SAMPLE VALIDATION")
    print(f"{'=' * 70}")
    params_str = ", ".join(f"{k}={v}" for k, v in result["params"].items())
    print(f"Params: {params_str}")
    print(f"{'':>20} {'Return%':>10} {'DD%':>8} {'PF':>8} {'WR%':>6} {'Trades':>7}")
    print(
        f"{'IS (60%)':>20} {result['IS_return']:>+10.2f} {result['IS_dd']:>8.2f} {result['IS_pf']:>8.2f} {result['IS_wr']:>5.1f}% {result['IS_trades']:>7d}"
    )
    print(
        f"{'OOS (40%)':>20} {result['OOS_return']:>+10.2f} {result['OOS_dd']:>8.2f} {result['OOS_pf']:>8.2f} {result['OOS_wr']:>5.1f}% {result['OOS_trades']:>7d}"
    )
    print()


def main():
    parser = argparse.ArgumentParser(description="15m Strategy Parameter Tuning")
    parser.add_argument(
        "--phase", choices=["single", "secondary", "multi", "oos", "all"], default="all"
    )
    parser.add_argument(
        "--multi-grid",
        type=str,
        default=None,
        help="JSON string overriding MULTI_GRID params",
    )
    parser.add_argument(
        "--oos-params",
        type=str,
        default=None,
        help="JSON string of params for OOS validation (e.g. '{\"ATR_STOP_MULT\": 5.5}')",
    )
    args = parser.parse_args()

    data = load_data(interval="15m", data_dir="backtest_data/15m_candles")
    if not data:
        print("ERROR: No data loaded")
        sys.exit(1)
    total_bars = sum(len(df) for df in data.values())
    print(f"Loaded {total_bars} bars across {len(data)} symbols: {list(data.keys())}")

    if args.phase in ("single", "all"):
        print("\n" + "=" * 70)
        print("PHASE 2: SINGLE-PARAMETER SWEEPS")
        print("=" * 70)
        for name, grid in SINGLE_SWEEPS:
            t0 = time.time()
            results = run_sweep(data, name, grid)
            print(f"  ({time.time() - t0:.1f}s)")
            print_results(results, name)

    if args.phase in ("secondary", "all"):
        print("\n" + "=" * 70)
        print("PHASE 3: SECONDARY SWEEPS")
        print("=" * 70)
        for name, grid in SECONDARY_SWEEPS:
            t0 = time.time()
            results = run_sweep(data, name, grid)
            print(f"  ({time.time() - t0:.1f}s)")
            print_results(results, name)

    if args.phase in ("multi", "all"):
        grid = MULTI_GRID
        if args.multi_grid:
            grid = json.loads(args.multi_grid)
        print("\n" + "=" * 70)
        print("PHASE 4: MULTI-PARAMETER GRID")
        print("=" * 70)
        t0 = time.time()
        results = run_sweep(data, "MULTI", grid)
        print(f"  ({time.time() - t0:.1f}s)")
        print_results(results, "MULTI")

    if args.phase == "oos":
        if args.oos_params:
            oos_overrides = json.loads(args.oos_params)
        else:
            oos_overrides = DEFAULTS.copy()
        print("\n" + "=" * 70)
        print("OUT-OF-SAMPLE VALIDATION")
        print("=" * 70)
        result = run_oos(data, oos_overrides)
        print_oos(result)

    reset_params()
    print("Done.")


if __name__ == "__main__":
    main()
