#!/usr/bin/env python3
"""
Daily Parameter Optimization Cron Job

Runs at midnight daily to:
1. Download maximum available 15m candle data from Hyperliquid
2. Run full parameter sweep optimization:
   - Single-parameter sweeps (subsampled, revalidated on full data)
   - Secondary sweeps (subsampled, revalidated on full data)
   - Forward stepwise accumulation of all validated results
   - Adaptive multi-parameter grid from stepwise best
   - Out-of-sample validation of final candidate
3. Save optimization results to Supabase PostgreSQL param_snapshots table
4. Save best parameters to active_params table (source of truth for strategy)
"""

import sys
import os
import time
import argparse
import multiprocessing as mp
import psycopg2
from dotenv import load_dotenv
import logging
from pathlib import Path
from datetime import datetime, timezone

BOT_ROOT = Path(__file__).resolve().parent.parent
for _p in (BOT_ROOT,):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

LOG_DIR = BOT_ROOT.parent / "logs"

logger = logging.getLogger("daily_tune")


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    log_file = LOG_DIR / f"daily_tune_{date_str}.log"

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
# Step 1: Data download
# ---------------------------------------------------------------------------
def download_max_15m_data() -> dict:
    from backtest.backtest_interval import download_all_data, load_data, cache_data_dir

    try:
        logger.info("Downloading 15m candles (hours_back=1300)...")
        data = download_all_data(hours_back=1300, interval="15m")
        if data:
            for sym, df in data.items():
                logger.info("  %s: %d bars", sym, len(df))
            return data
        logger.warning("download_all_data returned empty — trying cache fallback")
    except Exception as exc:
        logger.error("download_all_data failed: %s — trying cache fallback", exc)

    try:
        cdir = cache_data_dir("15m")
        data = load_data(interval="15m", data_dir=cdir)
        if data:
            for sym, df in data.items():
                logger.info("  %s: %d bars (cached)", sym, len(df))
            return data
    except Exception as exc:
        logger.error("Cache fallback also failed: %s", exc)

    return {}


# ---------------------------------------------------------------------------
# Step 2: Full optimization pipeline
# ---------------------------------------------------------------------------
def run_full_optimization(
    data: dict,
    n_workers: int = 4,
    subsample: int = 4,
    skip_oos: bool = False,
) -> tuple[dict, list[dict], dict | None]:
    """Run the complete optimisation pipeline.

    Returns:
        (best_params, all_validated_results, oos_result_or_None)
        best_params is a full parameter dict (DEFAULTS + overrides).
    """
    from backtest.tune_15m import (
        DEFAULTS,
        SINGLE_SWEEPS,
        SECONDARY_SWEEPS,
        build_adaptive_grid,
        run_sweep,
        score_result,
        forward_stepwise_accumulate,
        run_oos,
        subsample_data,
        revalidate,
    )

    # Prepare subsampled screening data
    screen_data = subsample_data(data, subsample) if subsample > 1 else data
    screen_bars = sum(len(df) for df in screen_data.values())
    full_bars = sum(len(df) for df in data.values())
    logger.info(
        "Screening data: %d bars (%.1fx speedup, every %dth bar)",
        screen_bars,
        full_bars / max(screen_bars, 1),
        subsample,
    )

    all_validated: list[dict] = []
    best_single_result = None

    # ---- Phase 1: Single-parameter sweeps (subsampled + revalidate) ----
    logger.info("Phase 1/4: Single-parameter sweeps (%d sweeps)...", len(SINGLE_SWEEPS))
    t0 = time.time()
    for name, grid in SINGLE_SWEEPS:
        logger.info("  Sweep: %s", name)
        try:
            results = run_sweep(
                screen_data,
                name,
                grid,
                n_workers=n_workers,
                subsample_factor=subsample,
            )
            if results:
                top_n = min(2, len(results))
                validated = revalidate(data, results, top_n=top_n)
                for r in validated:
                    r["sweep_name"] = name
                all_validated.extend(validated)
                for r in validated:
                    if (
                        best_single_result is None
                        or r["_score"] > best_single_result["_score"]
                    ):
                        best_single_result = r
                logger.info(
                    "  %s: %d screen -> %d validated",
                    name,
                    len(results),
                    len(validated),
                )
        except Exception as exc:
            logger.error("  Sweep %s failed: %s", name, exc)
    logger.info(
        "Single sweeps done in %.1fs (%d validated results)",
        time.time() - t0,
        len(all_validated),
    )

    # ---- Phase 2: Secondary sweeps (subsampled + revalidate) ----
    pre_secondary = len(all_validated)
    logger.info("Phase 2/4: Secondary sweeps (%d sweeps)...", len(SECONDARY_SWEEPS))
    t0 = time.time()
    for name, grid in SECONDARY_SWEEPS:
        logger.info("  Sweep: %s", name)
        try:
            results = run_sweep(
                screen_data,
                name,
                grid,
                n_workers=n_workers,
                subsample_factor=subsample,
            )
            if results:
                top_n = min(2, len(results))
                validated = revalidate(data, results, top_n=top_n)
                for r in validated:
                    r["sweep_name"] = name
                all_validated.extend(validated)
                for r in validated:
                    if (
                        best_single_result is None
                        or r["_score"] > best_single_result["_score"]
                    ):
                        best_single_result = r
                logger.info(
                    "  %s: %d screen -> %d validated",
                    name,
                    len(results),
                    len(validated),
                )
        except Exception as exc:
            logger.error("  Sweep %s failed: %s", name, exc)
    logger.info(
        "Secondary sweeps done in %.1fs (%d new, %d cumulative)",
        time.time() - t0,
        len(all_validated) - pre_secondary,
        len(all_validated),
    )

    # ---- Phase 3a: Forward stepwise accumulation ----
    logger.info("Phase 3a/4: Forward stepwise accumulation...")
    t0 = time.time()
    if all_validated:
        stepwise_params, stepwise_score = forward_stepwise_accumulate(
            data,
            all_validated,
        )
    else:
        stepwise_params = DEFAULTS.copy()
        stepwise_score = 0.0

    # Decide whether stepwise beats best single
    if best_single_result and stepwise_score < best_single_result["_score"]:
        logger.info(
            "  Stepwise score %.2f < best single %.2f — using best single params",
            stepwise_score,
            best_single_result["_score"],
        )
        best_params = dict(DEFAULTS)
        best_params.update(best_single_result["params"])
    else:
        logger.info(
            "  Stepwise score %.2f >= best single %.2f — using stepwise params",
            stepwise_score,
            best_single_result["_score"] if best_single_result else 0.0,
        )
        best_params = stepwise_params
    logger.info("Stepwise done in %.1fs", time.time() - t0)

    # ---- Phase 3b: Adaptive multi-parameter grid ----
    logger.info("Phase 3b/4: Adaptive multi-parameter grid...")
    t0 = time.time()
    try:
        grid = build_adaptive_grid(best_params)
        total_combos = 1
        for v in grid.values():
            total_combos *= len(v)
        logger.info(
            "  Adaptive grid: %d combos over %d params", total_combos, len(grid)
        )
        for k, v in grid.items():
            logger.info("    %s: %s", k, v)

        results = run_sweep(
            screen_data,
            "ADAPTIVE_MULTI",
            grid,
            n_workers=n_workers,
            subsample_factor=subsample,
        )
        if results:
            top_n = min(10, len(results))
            validated = revalidate(data, results, top_n=top_n)
            if validated:
                validated.sort(key=lambda x: x["_score"], reverse=True)
                for r in validated:
                    r["sweep_name"] = "ADAPTIVE_MULTI"
                best_params.update(validated[0]["params"])
                all_validated.extend(validated)
                logger.info(
                    "  Adaptive multi: %d screen -> %d validated, best score %.2f",
                    len(results),
                    len(validated),
                    validated[0]["_score"],
                )
    except Exception as exc:
        logger.error("  Adaptive multi-grid failed: %s", exc)
    logger.info("Adaptive multi-grid done in %.1fs", time.time() - t0)

    # ---- Phase 4: OOS validation ----
    oos_result = None
    if not skip_oos:
        logger.info("Phase 4/4: OOS validation...")
        t0 = time.time()
        try:
            oos_result = run_oos(data, best_params)
            deg = oos_result.get("degradation", float("inf"))
            if deg < 0.3:
                verdict = "PASS"
            elif deg < 0.6:
                verdict = "CAUTION"
            else:
                verdict = "FAIL — likely overfit"
            logger.info(
                "OOS: IS_score=%.2f OOS_score=%.2f degradation=%.1f%% [%s]",
                oos_result.get("IS_score", 0),
                oos_result.get("OOS_score", 0),
                deg * 100,
                verdict,
            )
        except Exception as exc:
            logger.error("  OOS validation failed: %s", exc)
        logger.info("OOS validation done in %.1fs", time.time() - t0)

    # Attach _ret_dd to all results for DB persistence compatibility
    for r in all_validated:
        dd = r.get("max_drawdown_pct", 0)
        r["_ret_dd"] = r.get("total_return_pct", 0) / max(dd, 0.01)

    return best_params, all_validated, oos_result


# ---------------------------------------------------------------------------
# Step 3: Best-result selection
# ---------------------------------------------------------------------------
def find_best_result(results: list[dict]) -> dict | None:
    valid = [
        r
        for r in results
        if r.get("total_return_pct", 0) > 0
        and r.get("max_drawdown_pct", 0) > 0
        and r.get("num_trades", 0) >= 10
    ]
    if not valid:
        logger.warning(
            "No valid results passed sanity filters (total=%d)", len(results)
        )
        return None
    # Use _score (computed by score_result in tune_15m) for ranking
    valid.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return valid[0]


# ---------------------------------------------------------------------------
# Step 4: Persist results to Supabase PostgreSQL
# ---------------------------------------------------------------------------
def save_to_database(
    best: dict | None,
    all_results: list[dict],
    period: str = "",
) -> None:
    from backtest.tune_15m import DEFAULTS

    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set — cannot save to database")
        return

    PARAM_COLUMNS = list(DEFAULTS.keys())

    conn = None
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        run_date = datetime.now(timezone.utc).isoformat()
        inserted = 0

        prev_snapshot_id = None
        cur.execute(
            "SELECT id FROM param_snapshots WHERE is_best = TRUE ORDER BY run_date DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            prev_snapshot_id = row[0]

        cols = (
            "run_date, sweep_name, sharpe, total_return_pct, "
            "max_drawdown_pct, profit_factor, win_rate_pct, "
            "num_trades, ret_dd_ratio, is_best, period, previous_snapshot_id, "
            + ", ".join(PARAM_COLUMNS)
        )
        placeholders = ", ".join(["%s"] * (12 + len(PARAM_COLUMNS)))

        for r in all_results:
            is_best = best is not None and r is best
            full_params = dict(DEFAULTS)
            full_params.update(r.get("params", {}))
            sweep_name = r.get("sweep_name", "")
            ret_dd = r.get("total_return_pct", 0) / max(
                r.get("max_drawdown_pct", 0.01), 0.01
            )

            values = [
                run_date,
                sweep_name,
                float(r.get("sharpe", 0)),
                float(r.get("total_return_pct", 0)),
                float(r.get("max_drawdown_pct", 0)),
                float(r.get("profit_factor", 0)),
                float(r.get("win_rate_pct", 0)),
                int(r.get("num_trades", 0)),
                float(ret_dd),
                is_best,
                period,
                prev_snapshot_id if is_best else None,
            ]
            for p in PARAM_COLUMNS:
                values.append(float(full_params[p]))

            cur.execute(
                f"INSERT INTO param_snapshots ({cols}) VALUES ({placeholders})",
                values,
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
# Helpers
# ---------------------------------------------------------------------------


def _compute_period(data: dict) -> str:
    starts, ends = [], []
    for df in data.values():
        ts = df["timestamp"]
        starts.append(int(ts.iloc[0]))
        ends.append(int(ts.iloc[-1]))
    if not starts:
        return ""
    from datetime import datetime, timezone

    fmt = "%Y-%m-%d"
    s = datetime.fromtimestamp(min(starts) / 1000, tz=timezone.utc).strftime(fmt)
    e = datetime.fromtimestamp(max(ends) / 1000, tz=timezone.utc).strftime(fmt)
    return f"{s}_{e}"


def _print_summary(
    best: dict | None,
    best_params: dict | None,
    oos_result: dict | None,
    total_results: int,
    elapsed: float,
) -> None:
    logger.info("=" * 60)
    logger.info("DAILY TUNE SUMMARY")
    logger.info("=" * 60)
    logger.info("Total optimisation results: %d", total_results)
    logger.info("Wall time: %.1fs", elapsed)

    if best is None:
        logger.info("No viable best result found — config NOT updated")
        return

    bp = best.get("params", {})
    logger.info("Best parameters:")
    for k in sorted(bp):
        logger.info("  %s = %s", k, bp[k])

    logger.info("Best metrics:")
    logger.info("  Score:           %.2f", best.get("_score", 0))
    logger.info("  Sharpe:          %.4f", best.get("sharpe", 0))
    logger.info("  Total return:    %.2f%%", best.get("total_return_pct", 0))
    logger.info("  Max drawdown:    %.2f%%", best.get("max_drawdown_pct", 0))
    logger.info("  Ret/DD ratio:    %.2f", best.get("_ret_dd", 0))
    logger.info("  Profit factor:   %.2f", best.get("profit_factor", 0))
    logger.info("  Win rate:        %.1f%%", best.get("win_rate_pct", 0))
    logger.info("  Trades:          %d", best.get("num_trades", 0))

    if oos_result:
        deg = oos_result.get("degradation", float("inf"))
        logger.info("OOS validation:")
        logger.info("  IS score:        %.2f", oos_result.get("IS_score", 0))
        logger.info("  OOS score:       %.2f", oos_result.get("OOS_score", 0))
        logger.info("  IS return:       %.2f%%", oos_result.get("IS_return", 0))
        logger.info("  OOS return:      %.2f%%", oos_result.get("OOS_return", 0))
        logger.info("  Degradation:     %.1f%%", deg * 100)

    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Parameter Optimization")
    parser.add_argument(
        "--workers",
        type=int,
        default=mp.cpu_count(),
        help=f"Parallel workers for sweeps (default={mp.cpu_count()})",
    )
    parser.add_argument(
        "--subsample",
        type=int,
        default=4,
        help="Take every Nth bar for screening (default=4)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip database persistence",
    )
    parser.add_argument(
        "--no-oos",
        action="store_true",
        help="Skip OOS validation",
    )
    args = parser.parse_args()

    t_start = time.time()
    load_dotenv()
    setup_logging()

    logger.info("=" * 60)
    logger.info(
        "DAILY PARAMETER OPTIMIZATION — %s", datetime.now(timezone.utc).isoformat()
    )
    logger.info("=" * 60)
    logger.info(
        "Config: workers=%d, subsample=%d, no-db=%s, no-oos=%s",
        args.workers,
        args.subsample,
        args.no_db,
        args.no_oos,
    )

    try:
        # 1. Download data
        logger.info("Step 1/4: Downloading data...")
        t0 = time.time()
        data = download_max_15m_data()
        if not data:
            logger.error("No data available — aborting")
            sys.exit(1)
        total_bars = sum(len(df) for df in data.values())
        logger.info(
            "Data ready: %d bars across %d symbols (%.1fs)",
            total_bars,
            len(data),
            time.time() - t0,
        )
        period = _compute_period(data)
        logger.info("Tuning period: %s", period)

        # 2. Run optimisation (sweeps + stepwise + adaptive grid + OOS)
        logger.info("Step 2/4: Running full optimisation...")
        t0 = time.time()
        best_params, all_results, oos_result = run_full_optimization(
            data,
            n_workers=args.workers,
            subsample=args.subsample,
            skip_oos=args.no_oos,
        )
        logger.info(
            "Optimisation complete: %d validated results (%.1fs)",
            len(all_results),
            time.time() - t0,
        )

        if not all_results:
            logger.error("Optimisation produced zero results — aborting")
            sys.exit(1)

        # 3. Find best result
        logger.info("Step 3/4: Selecting best result...")
        best = find_best_result(all_results)

        # 4. Save to database
        if not args.no_db:
            logger.info("Step 4/4: Saving to database...")
            save_to_database(best, all_results, period)
        else:
            logger.info("Step 4/4: Skipping database (--no-db)")

        # Save best to active_params table (source of truth for strategy)
        if best is not None and not args.no_db:
            try:
                from storage.active_params import save_active_params
                from backtest.tune_15m import DEFAULTS

                full_params = dict(DEFAULTS)
                full_params.update(best.get("params", {}))
                ret_dd = float(best.get("total_return_pct", 0)) / max(
                    float(best.get("max_drawdown_pct", 0.01)), 0.01
                )
                metrics = {
                    "sharpe": float(best.get("sharpe", 0)),
                    "total_return_pct": float(best.get("total_return_pct", 0)),
                    "max_drawdown_pct": float(best.get("max_drawdown_pct", 0)),
                    "profit_factor": float(best.get("profit_factor", 0)),
                    "win_rate_pct": float(best.get("win_rate_pct", 0)),
                    "num_trades": int(best.get("num_trades", 0)),
                    "ret_dd_ratio": ret_dd,
                }
                db_url = os.environ.get("SUPABASE_DB_URL", "")
                save_active_params(
                    db_url, period, best.get("sweep_name", ""), metrics, full_params
                )
                logger.info("Saved best result to active_params table")
            except Exception as exc:
                logger.error("Failed to save to active_params: %s", exc)

        # Summary
        elapsed = time.time() - t_start
        _print_summary(best, best_params, oos_result, len(all_results), elapsed)

    except Exception:
        logger.exception("Fatal error in daily_tune")
        sys.exit(1)


if __name__ == "__main__":
    main()
