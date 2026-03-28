#!/usr/bin/env python3
"""
Daily Parameter Optimization Cron Job

Runs at midnight daily to:
1. Download maximum available 15m candle data from Hyperliquid
2. Run full parameter sweep optimization (single + secondary + multi-grid)
3. Save optimization results to Supabase PostgreSQL param_snapshots table
4. Update config/optimized_params.json with best parameters
"""

import sys
import json
import os
import time
import psycopg2
from dotenv import load_dotenv
import logging
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOT_ROOT = Path(__file__).resolve().parent.parent
for _p in (BOT_ROOT, REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

CONFIG_PATH = BOT_ROOT / "config" / "optimized_params.json"
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
# Step 2: Optimization sweeps
# ---------------------------------------------------------------------------
def run_full_optimization(data: dict) -> list[dict]:
    from backtest.tune_15m import (
        SINGLE_SWEEPS,
        SECONDARY_SWEEPS,
        MULTI_GRID,
        run_sweep,
    )

    all_results: list[dict] = []

    logger.info("Phase 1/3: Single-parameter sweeps (%d sweeps)...", len(SINGLE_SWEEPS))
    t0 = time.time()
    for name, grid in SINGLE_SWEEPS:
        logger.info("  Sweep: %s", name)
        try:
            results = run_sweep(data, name, grid)
            _attach_ret_dd(results)
            all_results.extend(results)
            logger.info("  %s: %d valid results", name, len(results))
        except Exception as exc:
            logger.error("  Sweep %s failed: %s", name, exc)
    logger.info(
        "Single sweeps done in %.1fs (%d results)", time.time() - t0, len(all_results)
    )

    logger.info("Phase 2/3: Secondary sweeps (%d sweeps)...", len(SECONDARY_SWEEPS))
    t0 = time.time()
    for name, grid in SECONDARY_SWEEPS:
        logger.info("  Sweep: %s", name)
        try:
            results = run_sweep(data, name, grid)
            _attach_ret_dd(results)
            all_results.extend(results)
            logger.info("  %s: %d valid results", name, len(results))
        except Exception as exc:
            logger.error("  Sweep %s failed: %s", name, exc)
    pre_multi = len(all_results)
    logger.info(
        "Secondary sweeps done in %.1fs (%d cumulative)", time.time() - t0, pre_multi
    )

    logger.info("Phase 3/3: Multi-parameter grid...")
    t0 = time.time()
    try:
        results = run_sweep(data, "MULTI", MULTI_GRID)
        _attach_ret_dd(results)
        all_results.extend(results)
        logger.info("  MULTI: %d valid results", len(results))
    except Exception as exc:
        logger.error("  Multi-grid failed: %s", exc)
    logger.info(
        "Multi-grid done in %.1fs (total results: %d)",
        time.time() - t0,
        len(all_results),
    )

    return all_results


def _attach_ret_dd(results: list[dict]) -> None:
    for r in results:
        dd = r.get("max_drawdown_pct", 0)
        r["_ret_dd"] = r.get("total_return_pct", 0) / max(dd, 0.01)


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
    valid.sort(key=lambda x: x.get("_ret_dd", 0), reverse=True)
    return valid[0]


# ---------------------------------------------------------------------------
# Step 4: Persist results to Supabase PostgreSQL
# ---------------------------------------------------------------------------
def save_to_database(
    best: dict | None,
    all_results: list[dict],
    previous_params: dict | None,
) -> None:
    from backtest.tune_15m import DEFAULTS

    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set — cannot save to database")
        return

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

        for r in all_results:
            is_best = best is not None and r is best
            full_params = dict(DEFAULTS)
            full_params.update(r.get("params", {}))
            sweep_name = r.get("sweep_name", "")

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
                    run_date,
                    sweep_name,
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
        logger.info(
            "Saved %d snapshots (%d param_values each) to database",
            inserted,
            len(DEFAULTS),
        )
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
# Step 5: Update JSON config file
# ---------------------------------------------------------------------------
def update_config_file(best_params: dict) -> dict | None:
    from backtest.tune_15m import DEFAULTS

    previous_params: dict | None = None
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                previous_params = json.load(fh)
        except Exception as exc:
            logger.warning("Could not read existing config: %s", exc)

    full_params = dict(DEFAULTS)
    full_params.update(best_params)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(full_params, fh, indent=2)
            fh.write("\n")
        os.rename(tmp_path, CONFIG_PATH)
        logger.info("Updated config: %s", CONFIG_PATH)
    except Exception as exc:
        logger.error("Failed to write config: %s", exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    return previous_params


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_previous_params() -> dict | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _print_summary(
    best: dict | None,
    previous_params: dict | None,
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
    logger.info("  Sharpe:          %.4f", best.get("sharpe", 0))
    logger.info("  Total return:    %.2f%%", best.get("total_return_pct", 0))
    logger.info("  Max drawdown:    %.2f%%", best.get("max_drawdown_pct", 0))
    logger.info("  Ret/DD ratio:    %.2f", best.get("_ret_dd", 0))
    logger.info("  Profit factor:   %.2f", best.get("profit_factor", 0))
    logger.info("  Win rate:        %.1f%%", best.get("win_rate_pct", 0))
    logger.info("  Trades:          %d", best.get("num_trades", 0))

    if previous_params:
        changed = {
            k: (previous_params.get(k), bp.get(k))
            for k in sorted(set(list(previous_params.keys()) + list(bp.keys())))
            if previous_params.get(k) != bp.get(k)
        }
        if changed:
            logger.info("Changed from previous config:")
            for k, (old, new) in changed.items():
                logger.info("  %s: %s → %s", k, old, new)
        else:
            logger.info("No changes from previous config")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    t_start = time.time()
    load_dotenv()
    setup_logging()

    logger.info("=" * 60)
    logger.info(
        "DAILY PARAMETER OPTIMIZATION — %s", datetime.now(timezone.utc).isoformat()
    )
    logger.info("=" * 60)

    try:
        # 1. Download data
        logger.info("Step 1/5: Downloading data...")
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

        # 2. Run optimisation
        logger.info("Step 2/5: Running full optimisation...")
        t0 = time.time()
        all_results = run_full_optimization(data)
        logger.info(
            "Optimisation complete: %d total results (%.1fs)",
            len(all_results),
            time.time() - t0,
        )

        if not all_results:
            logger.error("Optimisation produced zero results — aborting")
            sys.exit(1)

        # 3. Find best result
        logger.info("Step 3/5: Selecting best result...")
        best = find_best_result(all_results)

        # 4. Load previous params & save everything to DB
        logger.info("Step 4/5: Saving to database...")
        previous_params = _load_previous_params()
        save_to_database(best, all_results, previous_params)

        # 5. Update config file
        logger.info("Step 5/5: Updating config file...")
        if best is not None:
            update_config_file(best["params"])
        else:
            logger.warning("No best result — config file left unchanged")

        # Summary
        elapsed = time.time() - t_start
        _print_summary(best, previous_params, len(all_results), elapsed)

    except Exception:
        logger.exception("Fatal error in daily_tune")
        sys.exit(1)


if __name__ == "__main__":
    main()
