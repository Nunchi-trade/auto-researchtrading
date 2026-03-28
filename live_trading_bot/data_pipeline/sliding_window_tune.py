#!/usr/bin/env python3
"""
Sliding Window Parameter Optimization

Runs daily_tune-style optimization for each day over the past 2 weeks.
Downloads 15m candle data once (enough for all windows), slices into 14
daily windows with the same 1300-hour lookback, and runs full optimization
(single + secondary + multi-grid sweeps) in parallel across 8 cores.

Usage:
    python sliding_window_tune.py
    python sliding_window_tune.py --workers 4
    python sliding_window_tune.py --days 7
"""

import sys
import json
import os
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup — same as daily_tune.py
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOT_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_DIR = Path(__file__).resolve().parent.parent / "backtest"
for _p in (BACKTEST_DIR, BOT_ROOT, REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

LOG_DIR = BOT_ROOT.parent / "logs"
RESULTS_DIR = BOT_ROOT.parent / "tuning_results"

logger = logging.getLogger("sliding_window_tune")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WINDOW_DAYS = 14  # How many days back to run windows
HOURS_BACK = 1300  # Same lookback as daily_tune.py
MAX_WORKERS = 8  # Parallel workers (user has 8 usable cores)
INTERVAL = "15m"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    log_file = LOG_DIR / f"sliding_window_tune_{date_str}.log"

    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(ch)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)


# ---------------------------------------------------------------------------
# Step 1: Download data once — enough for all windows
# ---------------------------------------------------------------------------
def download_full_data(total_hours: int) -> dict:
    from backtest.backtest_interval import (
        download_all_data,
        load_data,
        cache_data_dir,
        SYMBOLS,
    )

    needed_start_ms = int(time.time() * 1000) - (total_hours * 3600 * 1000)
    needed_bars_per_sym = total_hours * 4  # 4 bars/hour for 15m

    def _validate_coverage(data: dict) -> bool:
        if not data:
            return False
        for sym, df in data.items():
            oldest = df["timestamp"].min()
            if oldest > needed_start_ms + 3600 * 1000:
                logger.warning(
                    "  %s: cached data starts too late (%s vs needed %s)",
                    sym,
                    datetime.fromtimestamp(oldest / 1000, tz=timezone.utc).isoformat(),
                    datetime.fromtimestamp(
                        needed_start_ms / 1000, tz=timezone.utc
                    ).isoformat(),
                )
                return False
        return True

    try:
        logger.info("Downloading 15m candles (hours_back=%d)...", total_hours)
        data = download_all_data(hours_back=total_hours, interval=INTERVAL)
        if data and _validate_coverage(data):
            for sym, df in data.items():
                logger.info("  %s: %d bars", sym, len(df))
            return data
        if data:
            logger.warning("Cached data has insufficient range — forcing re-download")
            cdir = cache_data_dir(INTERVAL)
            for sym in SYMBOLS:
                fp = os.path.join(cdir, f"{sym}_{INTERVAL}.parquet")
                if os.path.exists(fp):
                    os.remove(fp)
            data = download_all_data(hours_back=total_hours, interval=INTERVAL)
            if data:
                for sym, df in data.items():
                    logger.info("  %s: %d bars (re-downloaded)", sym, len(df))
                return data
    except Exception as exc:
        logger.error("download_all_data failed: %s — trying cache fallback", exc)

    try:
        cdir = cache_data_dir(INTERVAL)
        data = load_data(interval=INTERVAL, data_dir=cdir)
        if data:
            for sym, df in data.items():
                logger.info("  %s: %d bars (cached)", sym, len(df))
            return data
    except Exception as exc:
        logger.error("Cache fallback also failed: %s", exc)

    return {}


# ---------------------------------------------------------------------------
# Step 2: Slice data for a specific window
# ---------------------------------------------------------------------------
def slice_data_for_window(
    full_data: dict, window_end_ms: int, lookback_hours: int
) -> dict:
    """Slice each symbol's DataFrame to [window_end - lookback, window_end]."""
    start_ms = window_end_ms - (lookback_hours * 3600 * 1000)
    sliced = {}
    for symbol, df in full_data.items():
        mask = (df["timestamp"] >= start_ms) & (df["timestamp"] <= window_end_ms)
        window_df = df.loc[mask].copy().reset_index(drop=True)
        if len(window_df) > 0:
            sliced[symbol] = window_df
    return sliced


# ---------------------------------------------------------------------------
# Step 3: Worker — run full optimization for one window (runs in subprocess)
# ---------------------------------------------------------------------------
def _run_window_worker(args: tuple) -> dict:
    """
    Subprocess worker. Receives (window_date_str, sliced_data, window_idx).
    Suppresses stdout to avoid interleaved progress bars from run_sweep.
    Returns dict with window metadata + results.
    """
    window_date_str, sliced_data, window_idx = args

    # Suppress stdout in worker — run_sweep prints progress bars
    old_stdout = sys.stdout
    sys.stdout = open(os.devnull, "w")

    try:
        from backtest.tune_15m import (
            SINGLE_SWEEPS,
            SECONDARY_SWEEPS,
            MULTI_GRID,
            run_sweep,
        )

        all_results: list[dict] = []

        # Phase 1: Single-parameter sweeps
        for name, grid in SINGLE_SWEEPS:
            try:
                results = run_sweep(sliced_data, name, grid)
                for r in results:
                    dd = r.get("max_drawdown_pct", 0)
                    r["_ret_dd"] = r.get("total_return_pct", 0) / max(dd, 0.01)
                    r["sweep_name"] = name
                all_results.extend(results)
            except Exception:
                pass

        # Phase 2: Secondary sweeps
        for name, grid in SECONDARY_SWEEPS:
            try:
                results = run_sweep(sliced_data, name, grid)
                for r in results:
                    dd = r.get("max_drawdown_pct", 0)
                    r["_ret_dd"] = r.get("total_return_pct", 0) / max(dd, 0.01)
                    r["sweep_name"] = name
                all_results.extend(results)
            except Exception:
                pass

        # Phase 3: Multi-parameter grid
        try:
            results = run_sweep(sliced_data, "MULTI", MULTI_GRID)
            for r in results:
                dd = r.get("max_drawdown_pct", 0)
                r["_ret_dd"] = r.get("total_return_pct", 0) / max(dd, 0.01)
                r["sweep_name"] = "MULTI"
            all_results.extend(results)
        except Exception:
            pass

        # Strip heavy fields from results (equity_curve, trade_log are large)
        for r in all_results:
            r.pop("equity_curve", None)
            r.pop("trade_log", None)
            r["window_date"] = window_date_str
            r["window_idx"] = window_idx

        # Find best result for this window
        best = _find_best_in_window(all_results)

        return {
            "window_date": window_date_str,
            "window_idx": window_idx,
            "num_results": len(all_results),
            "total_bars": sum(len(df) for df in sliced_data.values()),
            "results": all_results,
            "best": best,
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


def _find_best_in_window(results: list[dict]) -> dict | None:
    """Same selection logic as daily_tune.py find_best_result."""
    valid = [
        r
        for r in results
        if r.get("total_return_pct", 0) > 0
        and r.get("max_drawdown_pct", 0) > 0
        and r.get("num_trades", 0) >= 10
    ]
    if not valid:
        return None
    valid.sort(key=lambda x: x.get("_ret_dd", 0), reverse=True)
    return valid[0]


# ---------------------------------------------------------------------------
# Step 4: Save results to database (main process only)
# ---------------------------------------------------------------------------
def save_to_database(all_window_results: list[dict]) -> None:
    """Save all window results to param_snapshots with window_date tagging."""
    import psycopg2
    from backtest.tune_15m import DEFAULTS

    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set — cannot save to database")
        return

    conn = None
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        inserted = 0

        for wr in all_window_results:
            window_date = wr["window_date"]
            results = wr["results"]
            best = wr.get("best")

            # Find previous best snapshot (most recent overall)
            cur.execute(
                "SELECT id FROM param_snapshots WHERE is_best = TRUE "
                "ORDER BY run_date DESC LIMIT 1"
            )
            row = cur.fetchone()
            prev_snapshot_id = row[0] if row else None

            for r in results:
                is_best = best is not None and r is best
                full_params = dict(DEFAULTS)
                full_params.update(r.get("params", {}))
                sweep_name = r.get("sweep_name", "")
                # Tag sweep_name with window for disambiguation
                tagged_sweep = f"SW_{window_date}_{sweep_name}"

                cur.execute(
                    """
                    INSERT INTO param_snapshots
                        (run_date, sweep_name, sharpe, total_return_pct,
                         max_drawdown_pct, profit_factor, win_rate_pct,
                         num_trades, ret_dd_ratio, is_best, previous_snapshot_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        window_date,
                        tagged_sweep,
                        r.get("sharpe", 0),
                        r.get("total_return_pct", 0),
                        r.get("max_drawdown_pct", 0),
                        r.get("profit_factor", 0),
                        r.get("win_rate_pct", 0),
                        r.get("num_trades", 0),
                        r.get("_ret_dd", 0),
                        is_best,
                        prev_snapshot_id if is_best else None,
                    ),
                )
                fetched = cur.fetchone()
                if fetched is None:
                    continue
                snapshot_id = fetched[0]

                for param_name, param_value in full_params.items():
                    cur.execute(
                        """
                        INSERT INTO param_values (snapshot_id, param_name, param_value)
                        VALUES (%s, %s, %s)
                        """,
                        (snapshot_id, param_name, float(param_value)),
                    )
                inserted += 1

        conn.commit()
        logger.info("Saved %d snapshots to database", inserted)
    except Exception as exc:
        logger.error("Database insert failed: %s", exc)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Step 5: Save results to JSON
# ---------------------------------------------------------------------------
def save_results_json(all_window_results: list[dict]) -> None:
    """Save all results to a JSON file for offline analysis."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = RESULTS_DIR / f"sliding_window_{date_str}.json"

    # Prepare serializable output
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
                "sweep_name": b.get("sweep_name", ""),
                "params": b.get("params", {}),
                "sharpe": b.get("sharpe", 0),
                "total_return_pct": b.get("total_return_pct", 0),
                "max_drawdown_pct": b.get("max_drawdown_pct", 0),
                "_ret_dd": b.get("_ret_dd", 0),
                "profit_factor": b.get("profit_factor", 0),
                "win_rate_pct": b.get("win_rate_pct", 0),
                "num_trades": b.get("num_trades", 0),
            }

        # Sort by _ret_dd and take top 5
        sorted_results = sorted(
            wr["results"], key=lambda x: x.get("_ret_dd", 0), reverse=True
        )
        for r in sorted_results[:5]:
            entry["top5"].append(
                {
                    "sweep_name": r.get("sweep_name", ""),
                    "params": r.get("params", {}),
                    "sharpe": r.get("sharpe", 0),
                    "total_return_pct": r.get("total_return_pct", 0),
                    "max_drawdown_pct": r.get("max_drawdown_pct", 0),
                    "_ret_dd": r.get("_ret_dd", 0),
                    "profit_factor": r.get("profit_factor", 0),
                    "win_rate_pct": r.get("win_rate_pct", 0),
                    "num_trades": r.get("num_trades", 0),
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


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def print_summary(all_window_results: list[dict], elapsed: float) -> None:
    logger.info("=" * 70)
    logger.info("SLIDING WINDOW TUNE SUMMARY")
    logger.info("=" * 70)
    logger.info("Windows:    %d", len(all_window_results))
    logger.info("Workers:    %d", MAX_WORKERS)
    logger.info("Wall time:  %.1fs", elapsed)

    total_results = sum(wr["num_results"] for wr in all_window_results)
    logger.info("Total optimization results: %d", total_results)

    for wr in sorted(all_window_results, key=lambda x: x["window_idx"]):
        best = wr.get("best")
        if best:
            bp = best.get("params", {})
            logger.info(
                "  Window %s: %d results, best Ret/DD=%.2f Sharpe=%.4f Return=%.2f%% DD=%.2f%% Trades=%d",
                wr["window_date"],
                wr["num_results"],
                best.get("_ret_dd", 0),
                best.get("sharpe", 0),
                best.get("total_return_pct", 0),
                best.get("max_drawdown_pct", 0),
                best.get("num_trades", 0),
            )
            # Log changed params from defaults
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Sliding Window Parameter Optimization"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=WINDOW_DAYS,
        help=f"Number of days back (default: {WINDOW_DAYS})",
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
        "--no-db",
        action="store_true",
        help="Skip database save (JSON only)",
    )
    args = parser.parse_args()

    t_start = time.time()
    load_dotenv()
    setup_logging()

    num_days = args.days
    workers = args.workers
    lookback_hours = args.lookback

    logger.info("=" * 70)
    logger.info(
        "SLIDING WINDOW PARAMETER OPTIMIZATION — %s",
        datetime.now(timezone.utc).isoformat(),
    )
    logger.info("=" * 70)
    logger.info(
        "Config: %d days, %d workers, %dh lookback per window",
        num_days,
        workers,
        lookback_hours,
    )

    try:
        # 1. Download data once — need enough for (num_days + lookback)
        total_hours = num_days * 24 + lookback_hours
        logger.info("Step 1/4: Downloading data (%d hours back)...", total_hours)
        t0 = time.time()
        full_data = download_full_data(total_hours)
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

        # Show data time range
        import pandas as pd

        all_ts = []
        for df in full_data.values():
            all_ts.extend(df["timestamp"].tolist())
        if all_ts:
            first_t = pd.Timestamp(min(all_ts), unit="ms", tz="UTC")
            last_t = pd.Timestamp(max(all_ts), unit="ms", tz="UTC")
            logger.info("Data range: %s to %s", first_t, last_t)

        # 2. Build window tasks
        logger.info("Step 2/4: Preparing %d daily windows...", num_days)
        now = datetime.now(timezone.utc)
        tasks = []
        for i in range(num_days):
            # Each window ends at midnight UTC of that day
            # Day 0 = today, Day 1 = yesterday, etc.
            window_end = now - timedelta(days=i)
            # Round to midnight UTC of that day for consistency
            window_end = window_end.replace(hour=0, minute=0, second=0, microsecond=0)
            window_end_ms = int(window_end.timestamp() * 1000)
            window_date_str = window_end.strftime("%Y-%m-%d")

            sliced = slice_data_for_window(full_data, window_end_ms, lookback_hours)
            window_bars = sum(len(df) for df in sliced.values())
            logger.info(
                "  Window %2d (%s): %d bars across %d symbols",
                i,
                window_date_str,
                window_bars,
                len(sliced),
            )
            tasks.append((window_date_str, sliced, i))

        # 3. Run optimization in parallel
        logger.info(
            "Step 3/4: Running optimization in parallel (%d workers)...", workers
        )
        t0 = time.time()
        all_window_results = []

        with ProcessPoolExecutor(max_workers=workers) as executor:
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
                    best_ret_dd = 0
                    if result.get("best"):
                        best_ret_dd = result["best"].get("_ret_dd", 0)
                    logger.info(
                        "  [%2d/%d] Window %s done: %d results, best Ret/DD=%.2f",
                        completed,
                        len(tasks),
                        window_date,
                        result["num_results"],
                        best_ret_dd,
                    )
                except Exception as exc:
                    logger.error(
                        "  Window %s (idx=%d) FAILED: %s",
                        window_date,
                        window_idx,
                        exc,
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

        # Sort by window_idx for consistent ordering
        all_window_results.sort(key=lambda x: x["window_idx"])

        logger.info(
            "Optimization complete: %d windows processed (%.1fs)",
            len(all_window_results),
            time.time() - t0,
        )

        # 4. Save results
        logger.info("Step 4/4: Saving results...")
        save_results_json(all_window_results)

        if not args.no_db:
            save_to_database(all_window_results)
        else:
            logger.info("Database save skipped (--no-db)")

        # Summary
        elapsed = time.time() - t_start
        print_summary(all_window_results, elapsed)

    except Exception:
        logger.exception("Fatal error in sliding_window_tune")
        sys.exit(1)


if __name__ == "__main__":
    main()
