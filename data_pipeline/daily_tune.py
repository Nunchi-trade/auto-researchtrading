#!/usr/bin/env python3
"""Daily Parameter Optimization Cron Job

Downloads 15m candle data, then delegates to tune_15m.py --phase all
for per-symbol parameter optimisation. Parses the JSON results and
saves one row per symbol to param_snapshots (is_active = TRUE).
"""

import json
import logging
import subprocess
import sys
import time
import argparse
import multiprocessing as mp
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone

import common
from common import (
    PIPELINE_ROOT,
    RESULTS_DIR,
    setup_logging,
    download_15m_data,
    compute_period,
    save_snapshots_to_db,
)

logger = logging.getLogger("daily_tune")  # noqa: F821


def _run_tune_15m(workers: int, subsample: int) -> Path:
    """Shell out to tune_15m.py --phase all. Returns path to the JSON results file."""
    tune_script = PIPELINE_ROOT / "backtest" / "tune_15m.py"
    cmd = [
        sys.executable,
        str(tune_script),
        "--phase",
        "all",
        "--workers",
        str(workers),
        "--subsample",
        str(subsample),
    ]
    logger.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=False)
    if proc.returncode != 0:
        raise RuntimeError(f"tune_15m.py exited with code {proc.returncode}")

    json_files = sorted(RESULTS_DIR.glob("tune_15m_*.json"), reverse=True)
    if not json_files:
        raise RuntimeError("tune_15m.py produced no JSON results file")
    return json_files[0]


def _parse_results(json_path: Path) -> dict:
    """Parse tune_15m JSON output into structured data."""
    with open(json_path) as f:
        data = json.load(f)

    result = {
        "best_params": data.get("best_params", {}),
        "best_score": data.get("best_score", 0),
        "per_symbol_params": data.get("per_symbol_best_params", {}),
        "per_symbol_scores": data.get("per_symbol_best_scores", {}),
        "walk_forward_pass": data.get("walk_forward_pass"),
        "walk_forward_avg_return": data.get("walk_forward_avg_return"),
        "stability_pass": data.get("stability_pass"),
        "top10": data.get("top10_results", []),
        "results_file": str(json_path),
    }
    return result


def _print_summary(parsed: dict, elapsed: float):
    logger.info("=" * 60)
    logger.info("DAILY TUNE SUMMARY")
    logger.info("=" * 60)
    logger.info("Wall time: %.1fs", elapsed)
    logger.info("Results file: %s", parsed["results_file"])
    logger.info("Overall best score: %.2f", parsed["best_score"])

    if parsed["per_symbol_params"]:
        logger.info("Per-symbol results:")
        for symbol, params in sorted(parsed["per_symbol_params"].items()):
            score = parsed["per_symbol_scores"].get(symbol, 0)
            logger.info("  %s: score=%.2f  params=%s", symbol, score, params)
    else:
        logger.warning("No per-symbol results — tune_15m may not have run --phase all")

    if parsed["walk_forward_pass"] is not None:
        logger.info(
            "Walk-forward: %s", "PASS" if parsed["walk_forward_pass"] else "FAIL"
        )
        if parsed["walk_forward_avg_return"] is not None:
            logger.info("  Avg test return: %.2f%%", parsed["walk_forward_avg_return"])

    if parsed["stability_pass"] is not None:
        logger.info("Stability: %s", "PASS" if parsed["stability_pass"] else "FAIL")

    if parsed["top10"]:
        logger.info("Top 10 results:")
        for i, r in enumerate(parsed["top10"]):
            logger.info(
                "  %2d. Score=%.2f  Sharpe=%.2f  Return=%+.1f%%  DD=%.1f%%  Trades=%d",
                i + 1,
                r.get("score", 0),
                r.get("sharpe_ann", 0),
                r.get("return_pct", 0),
                r.get("dd_pct", 0),
                r.get("trades", 0),
            )

    logger.info("=" * 60)


def main():
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
        "--no-db", action="store_true", help="Skip database persistence"
    )
    args = parser.parse_args()

    t_start = time.time()
    load_dotenv()
    setup_logging("daily_tune", "daily_tune")

    logger.info("=" * 60)
    logger.info(
        "DAILY PARAMETER OPTIMIZATION — %s", datetime.now(timezone.utc).isoformat()
    )
    logger.info("=" * 60)
    logger.info(
        "Config: workers=%d, subsample=%d, no-db=%s",
        args.workers,
        args.subsample,
        args.no_db,
    )

    try:
        logger.info("Step 1/3: Downloading data...")
        t0 = time.time()
        data = download_15m_data(hours_back=1300, interval="15m", logger=logger)
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
        period = compute_period(data)
        logger.info("Tuning period: %s", period)

        logger.info("Step 2/3: Running per-symbol optimisation via tune_15m...")
        t0 = time.time()
        json_path = _run_tune_15m(
            workers=args.workers,
            subsample=args.subsample,
        )
        logger.info("tune_15m completed in %.1fs", time.time() - t0)

        logger.info("Step 3/3: Parsing results...")
        parsed = _parse_results(json_path)

        if not args.no_db:
            logger.info("Saving per-symbol results to database...")
            n = save_snapshots_to_db(parsed, period)
            logger.info("Saved %d snapshot(s)", n)
        else:
            logger.info("Skipping database (--no-db)")

        _print_summary(parsed, time.time() - t_start)

    except Exception:
        logger.exception("Fatal error in daily_tune")
        sys.exit(1)


if __name__ == "__main__":
    main()
