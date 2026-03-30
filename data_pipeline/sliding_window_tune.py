#!/usr/bin/env python3
"""Sliding Window Parameter Optimization

Runs daily_tune-style optimisation for each day over the past N days.
Downloads 15m candle data once (enough for all windows), slices into daily
windows, and runs full optimisation in parallel across workers.

Usage:
    python sliding_window_tune.py
    python sliding_window_tune.py --workers 4
    python sliding_window_tune.py --days 7
    python sliding_window_tune.py --subsample 4
"""

import sys
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from dotenv import load_dotenv

import common
from common import (
    setup_logging,
    download_15m_data,
    compute_period,
    find_best_result,
    save_snapshots_to_db,
    run_optimization_pipeline,
    RESULTS_DIR,
)

logger = logging.getLogger("sliding_window_tune")  # noqa: F821

WINDOW_DAYS = 14
HOURS_BACK = 1300
MAX_WORKERS = 8
INTERVAL = "15m"


def slice_data_for_window(
    full_data: dict, window_end_ms: int, lookback_hours: int
) -> dict:
    start_ms = window_end_ms - (lookback_hours * 3600 * 1000)
    sliced = {}
    for symbol, df in full_data.items():
        mask = (df["timestamp"] >= start_ms) & (df["timestamp"] <= window_end_ms)
        window_df = df.loc[mask].copy().reset_index(drop=True)
        if len(window_df) > 0:
            sliced[symbol] = window_df
    return sliced


def _run_window_worker(args: tuple) -> dict:
    """Subprocess worker: run optimisation for one window."""
    window_date_str, sliced_data, window_idx, subsample_factor = args

    old_stdout = sys.stdout
    sys.stdout = open(os.devnull, "w")
    try:
        _, all_results, _ = run_optimization_pipeline(
            sliced_data,
            n_workers=1,  # parallelism is at window level, not within
            subsample=subsample_factor,
            skip_oos=True,
            logger=None,
        )

        for r in all_results:
            r.pop("equity_curve", None)
            r.pop("trade_log", None)
            r["window_date"] = window_date_str
            r["window_idx"] = window_idx

        best = find_best_result(all_results)
        period = compute_period(sliced_data)

        return {
            "window_date": window_date_str,
            "window_idx": window_idx,
            "num_results": len(all_results),
            "total_bars": sum(len(df) for df in sliced_data.values()),
            "results": all_results,
            "best": best,
            "period": period,
        }
    except Exception as exc:
        return {
            "window_date": window_date_str,
            "window_idx": window_idx,
            "num_results": 0,
            "total_bars": 0,
            "results": [],
            "best": None,
            "error": str(exc),
        }
    finally:
        sys.stdout.close()
        sys.stdout = old_stdout


def save_results_json(all_window_results: list[dict]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = RESULTS_DIR / f"sliding_window_{date_str}.json"

    output = []
    for wr in all_window_results:
        entry = {
            "window_date": wr["window_date"],
            "window_idx": wr["window_idx"],
            "total_bars": wr["total_bars"],
            "num_results": wr["num_results"],
            "error": wr.get("error"),
            "best": None,
            "top5": [],
        }
        if wr.get("best"):
            b = wr["best"]
            entry["best"] = {
                k: b.get(k, 0) if k != "sweep_name" else b.get(k, "")
                for k in (
                    "sweep_name",
                    "params",
                    "sharpe",
                    "total_return_pct",
                    "max_drawdown_pct",
                    "_score",
                    "profit_factor",
                    "win_rate_pct",
                    "num_trades",
                )
            }
        sorted_results = sorted(
            wr["results"], key=lambda x: x.get("_score", 0), reverse=True
        )
        for r in sorted_results[:5]:
            entry["top5"].append(
                {
                    k: r.get(k, 0)
                    if k not in ("sweep_name", "params")
                    else r.get(k, "")
                    for k in (
                        "sweep_name",
                        "params",
                        "sharpe",
                        "total_return_pct",
                        "max_drawdown_pct",
                        "_score",
                        "profit_factor",
                        "win_rate_pct",
                        "num_trades",
                    )
                }
            )
        output.append(entry)

    tmp_path = filepath.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2)
            fh.write("\n")
        os.rename(tmp_path, filepath)
        logger.info("Results saved to: %s", filepath)
    except Exception as exc:
        logger.error("Failed to write JSON: %s", exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def print_summary(all_window_results: list[dict], elapsed: float) -> None:
    logger.info("=" * 70)
    logger.info("SLIDING WINDOW TUNE SUMMARY")
    logger.info("=" * 70)
    logger.info("Windows:    %d", len(all_window_results))
    logger.info("Workers:    %d", MAX_WORKERS)
    logger.info("Wall time:  %.1fs", elapsed)

    total_results = sum(wr["num_results"] for wr in all_window_results)
    logger.info("Total optimisation results: %d", total_results)

    for wr in sorted(all_window_results, key=lambda x: x["window_idx"]):
        best = wr.get("best")
        if best:
            bp = best.get("params", {})
            logger.info(
                "  Window %s: %d results, best Score=%.2f Sharpe=%.4f Return=%.2f%% DD=%.2f%% Trades=%d",
                wr["window_date"],
                wr["num_results"],
                best.get("_score", 0),
                best.get("sharpe", 0),
                best.get("total_return_pct", 0),
                best.get("max_drawdown_pct", 0),
                best.get("num_trades", 0),
            )
            from backtest.tune_15m import DEFAULTS

            changed = {k: v for k, v in bp.items() if DEFAULTS.get(k) != v}
            if changed:
                logger.info(
                    "    Changed: %s",
                    ", ".join(f"{k}={v}" for k, v in sorted(changed.items())),
                )
        else:
            logger.info(
                "  Window %s: %d results, no viable best",
                wr["window_date"],
                wr["num_results"],
            )

    logger.info("=" * 70)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Sliding Window Parameter Optimization"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=WINDOW_DAYS,
        help=f"Days back (default: {WINDOW_DAYS})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Parallel workers (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=HOURS_BACK,
        help=f"Lookback hours per window (default: {HOURS_BACK})",
    )
    parser.add_argument(
        "--no-db", action="store_true", help="Skip database save (JSON only)"
    )
    parser.add_argument(
        "--subsample", type=int, default=1, help="Take every Nth bar (default=1)"
    )
    args = parser.parse_args()

    t_start = time.time()
    load_dotenv()
    setup_logging("sliding_window_tune", "sliding_window_tune")

    logger.info("=" * 70)
    logger.info(
        "SLIDING WINDOW PARAMETER OPTIMIZATION — %s",
        datetime.now(timezone.utc).isoformat(),
    )
    logger.info("=" * 70)
    logger.info(
        "Config: %d days, %d workers, %dh lookback per window",
        args.days,
        args.workers,
        args.lookback,
    )

    try:
        total_hours = args.days * 24 + args.lookback
        logger.info("Step 1/4: Downloading data (%d hours back)...", total_hours)
        t0 = time.time()
        full_data = download_15m_data(
            hours_back=total_hours, interval=INTERVAL, logger=logger
        )
        if not full_data:
            logger.error("No data available — aborting")
            sys.exit(1)

        total_bars = sum(len(df) for df in full_data.values())
        logger.info(
            "Data ready: %d bars across %d symbols (%.1fs)",
            total_bars,
            len(full_data),
            time.time() - t0,
        )

        logger.info("Step 2/4: Preparing %d daily windows...", args.days)
        now = datetime.now(timezone.utc)
        tasks = []
        for i in range(args.days):
            window_end = now - timedelta(days=i)
            window_end = window_end.replace(hour=0, minute=0, second=0, microsecond=0)
            window_end_ms = int(window_end.timestamp() * 1000)
            window_date_str = window_end.strftime("%Y-%m-%d")

            sliced = slice_data_for_window(full_data, window_end_ms, args.lookback)
            window_bars = sum(len(df) for df in sliced.values())
            logger.info(
                "  Window %2d (%s): %d bars across %d symbols",
                i,
                window_date_str,
                window_bars,
                len(sliced),
            )
            tasks.append((window_date_str, sliced, i, args.subsample))

        logger.info(
            "Step 3/4: Running optimisation in parallel (%d workers)...", args.workers
        )
        t0 = time.time()
        all_window_results = []

        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(_run_window_worker, task): task for task in tasks
            }
            completed = 0
            for future in as_completed(futures):
                task = futures[future]
                window_date = task[0]
                window_idx = task[2]
                try:
                    result = future.result()
                    all_window_results.append(result)
                    completed += 1
                    best_score = (
                        result["best"].get("_score", 0) if result.get("best") else 0
                    )
                    logger.info(
                        "  [%2d/%d] Window %s done: %d results, best Score=%.2f",
                        completed,
                        len(tasks),
                        window_date,
                        result["num_results"],
                        best_score,
                    )
                except Exception as exc:
                    logger.error(
                        "  Window %s (idx=%d) FAILED: %s", window_date, window_idx, exc
                    )
                    all_window_results.append(
                        {
                            "window_date": window_date,
                            "window_idx": window_idx,
                            "num_results": 0,
                            "total_bars": 0,
                            "results": [],
                            "best": None,
                            "error": str(exc),
                        }
                    )

        all_window_results.sort(key=lambda x: x["window_idx"])
        logger.info(
            "Optimisation complete: %d windows (%.1fs)",
            len(all_window_results),
            time.time() - t0,
        )

        logger.info("Step 4/4: Saving results...")
        save_results_json(all_window_results)

        if not args.no_db:
            snapshots = []
            for wr in all_window_results:
                best = wr.get("best")
                if best:
                    tag = f"SW_{wr['window_date']}_{best.get('sweep_name', '')}"
                    snapshots.append((best, wr.get("period", ""), tag))
            n = save_snapshots_to_db(snapshots)
            logger.info("Saved %d snapshot(s) to database", n)
        else:
            logger.info("Database save skipped (--no-db)")

        print_summary(all_window_results, time.time() - t_start)

    except Exception:
        logger.exception("Fatal error in sliding_window_tune")
        sys.exit(1)


if __name__ == "__main__":
    main()
