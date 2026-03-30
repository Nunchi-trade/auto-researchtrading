"""Shared utilities for data_pipeline cron scripts.

Centralises duplicated logic from daily_tune.py and sliding_window_tune.py:
- Path setup (auto-runs on import)
- Logging configuration
- 15m candle data download with cache fallback
- Period string computation
- Best-result selection
- Supabase param_snapshots persistence
- Core optimisation pipeline (sweeps → stepwise → adaptive grid → walk-forward)
"""

import sys
import os
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Path constants — auto-setup on import
# ---------------------------------------------------------------------------
PIPELINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PIPELINE_ROOT.parent
LIVE_BOT_ROOT = REPO_ROOT / "live_trading_bot"
LOG_DIR = PIPELINE_ROOT / "logs"
RESULTS_DIR = PIPELINE_ROOT / "tuning_results"

# Ensure pipeline root and live_trading_bot are importable; exclude bare repo root
# so `import strategies` resolves to live_trading_bot, not repo-level modules.
for _p in (PIPELINE_ROOT, LIVE_BOT_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
sys.path = [p for p in sys.path if Path(p).resolve() != REPO_ROOT]
# Append (not insert) REPO_ROOT so `import constants` resolves, while
# `import backtest` still hits data_pipeline/backtest/ (PIPELINE_ROOT is at front).
sys.path.append(str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(name: str, log_prefix: str) -> logging.Logger:
    """Configure console (INFO) + file (DEBUG) logging. Returns configured logger."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    log_file = LOG_DIR / f"{log_prefix}_{date_str}.log"

    log = logging.getLogger(name)
    if log.handlers:  # already configured (e.g. re-import in interactive session)
        return log
    log.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    log.addHandler(ch)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)

    return log


# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------
def download_15m_data(
    hours_back: int = 1300,
    interval: str = "15m",
    logger: logging.Logger | None = None,
) -> dict:
    """Download candle data with cache fallback.

    Validates that downloaded data covers the requested range; if not, clears
    stale cache entries and retries once before falling back to whatever is cached.
    """
    from backtest.backtest_interval import (
        download_all_data,
        load_data,
        cache_data_dir,
    )

    _info = logger.info if logger else lambda *a, **kw: None
    _warn = logger.warning if logger else lambda *a, **kw: None
    _err = logger.error if logger else lambda *a, **kw: None

    needed_start_ms = int(time.time() * 1000) - (hours_back * 3600 * 1000)

    def _covers(data: dict) -> bool:
        if not data:
            return False
        for sym, df in data.items():
            if df["timestamp"].min() > needed_start_ms + 3600 * 1000:
                return False
        return True

    # Primary: fresh download
    try:
        _info("Downloading %s candles (hours_back=%d)...", interval, hours_back)
        data = download_all_data(hours_back=hours_back, interval=interval)
        if data and _covers(data):
            for sym, df in data.items():
                _info("  %s: %d bars", sym, len(df))
            return data
        # Download succeeded but range is insufficient — clear stale cache & retry
        if data:
            _warn("Cached data has insufficient range — forcing re-download")
            try:
                from backtest.backtest_interval import SYMBOLS

                cdir = cache_data_dir(interval)
                for sym in SYMBOLS:
                    fp = os.path.join(cdir, f"{sym}_{interval}.parquet")
                    if os.path.exists(fp):
                        os.remove(fp)
            except Exception:
                pass
            data = download_all_data(hours_back=hours_back, interval=interval)
            if data:
                for sym, df in data.items():
                    _info("  %s: %d bars (re-downloaded)", sym, len(df))
                return data
    except Exception as exc:
        _err("download_all_data failed: %s — trying cache fallback", exc)

    # Fallback: load from cache
    try:
        cdir = cache_data_dir(interval)
        data = load_data(interval=interval, data_dir=cdir)
        if data:
            for sym, df in data.items():
                _info("  %s: %d bars (cached)", sym, len(df))
            return data
    except Exception as exc:
        _err("Cache fallback also failed: %s", exc)

    return {}


# ---------------------------------------------------------------------------
# Period computation
# ---------------------------------------------------------------------------
def compute_period(data: dict) -> str:
    """Return 'YYYY-MM-DD_YYYY-MM-DD' from data timestamps."""
    starts, ends = [], []
    for df in data.values():
        ts = df["timestamp"]
        starts.append(int(ts.iloc[0]))
        ends.append(int(ts.iloc[-1]))
    if not starts:
        return ""
    fmt = "%Y-%m-%d"
    s = datetime.fromtimestamp(min(starts) / 1000, tz=timezone.utc).strftime(fmt)
    e = datetime.fromtimestamp(max(ends) / 1000, tz=timezone.utc).strftime(fmt)
    return f"{s}_{e}"


# ---------------------------------------------------------------------------
# Best result selection
# ---------------------------------------------------------------------------
def find_best_result(results: list[dict]) -> dict | None:
    """Select best result: positive return, positive DD, >= 10 trades, highest score."""
    valid = [
        r
        for r in results
        if r.get("total_return_pct", 0) > 0
        and r.get("max_drawdown_pct", 0) > 0
        and r.get("num_trades", 0) >= 10
    ]
    if not valid:
        return None
    valid.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return valid[0]


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------
def save_snapshots_to_db(
    parsed: dict,
    period: str = "",
) -> int:
    """Save per-symbol best params to param_snapshots.

    Args:
        parsed: dict from _parse_results() with per_symbol_params,
                per_symbol_scores, top10, etc.
        period: tuning period string (e.g. '2026-02-06_2026-03-30').

    Returns:
        Number of rows inserted.
    """
    import psycopg2
    from backtest.tune_15m import DEFAULTS

    log = logging.getLogger("daily_tune")

    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        return 0

    PARAM_COLUMNS = list(DEFAULTS.keys())
    conn = None
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        cur.execute(
            "SELECT id FROM param_snapshots WHERE is_active = TRUE "
            "ORDER BY run_date DESC LIMIT 1"
        )
        row = cur.fetchone()
        prev_id = row[0] if row else None

        cur.execute(
            "UPDATE param_snapshots SET is_active = FALSE WHERE is_active = TRUE"
        )

        cols = (
            "run_date, sweep_name, sharpe, total_return_pct, "
            "max_drawdown_pct, profit_factor, win_rate_pct, "
            "num_trades, ret_dd_ratio, is_best, is_active, period, "
            "previous_snapshot_id, symbol, " + ", ".join(PARAM_COLUMNS)
        )
        placeholders = ", ".join(["%s"] * (14 + len(PARAM_COLUMNS)))

        run_date = datetime.now(timezone.utc).isoformat()
        inserted = 0

        for symbol, params in (parsed.get("per_symbol_params") or {}).items():
            score = parsed.get("per_symbol_scores", {}).get(symbol, 0)
            if score <= 0:
                log.info("Skipping %s (score=%.2f, no improvement)", symbol, score)
                continue

            full_params = dict(DEFAULTS)
            full_params.update(params)

            values = [
                run_date,
                "daily_tune",
                score,
                0.0,
                0.0,
                0.0,
                0.0,
                0,
                0.0,
                True,
                True,
                period,
                prev_id,
                symbol,
            ]
            for p in PARAM_COLUMNS:
                values.append(float(full_params.get(p, DEFAULTS.get(p, 0))))

            cur.execute(
                f"INSERT INTO param_snapshots ({cols}) VALUES ({placeholders})",
                values,
            )
            inserted += 1

        conn.commit()
        return inserted
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return 0
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Core optimisation pipeline
# ---------------------------------------------------------------------------
def run_optimization_pipeline(
    data: dict,
    n_workers: int = 4,
    subsample: int = 4,
    skip_oos: bool = False,
    logger: logging.Logger | None = None,
) -> tuple[dict, list[dict], dict | None]:
    """Run the complete optimisation pipeline.

    Phases:
        1. Single-parameter sweeps (subsampled, revalidated)
        2. Secondary sweeps (subsampled, revalidated)
        3a. Forward stepwise accumulation
        3b. Adaptive multi-parameter grid
        4. Walk-forward validation (optional)

    Returns:
        ``(best_params, all_validated_results, wf_result_or_None)``
    """
    from backtest.tune_15m import (
        DEFAULTS,
        SINGLE_SWEEPS,
        SECONDARY_SWEEPS,
        build_adaptive_grid,
        run_sweep,
        forward_stepwise_accumulate,
        run_walk_forward,
        subsample_data,
        revalidate,
    )

    _info = logger.info if logger else lambda *a, **kw: None
    _err = logger.error if logger else lambda *a, **kw: None

    # Subsampled screening data
    screen_data = subsample_data(data, subsample) if subsample > 1 else data
    screen_bars = sum(len(df) for df in screen_data.values())
    full_bars = sum(len(df) for df in data.values())
    _info(
        "Screening data: %d bars (%.1fx speedup, every %dth bar)",
        screen_bars,
        full_bars / max(screen_bars, 1),
        subsample,
    )

    all_validated: list[dict] = []
    best_single_result = None

    # ---- Helper: run a batch of sweeps ----
    def _sweep_phase(sweeps, phase_label):
        nonlocal best_single_result
        _info("%s (%d sweeps)...", phase_label, len(sweeps))
        t0 = time.time()
        pre = len(all_validated)
        for name, grid in sweeps:
            _info("  Sweep: %s", name)
            try:
                results = run_sweep(
                    screen_data,
                    name,
                    grid,
                    n_workers=n_workers,
                    subsample_factor=subsample,
                )
                if results:
                    validated = revalidate(data, results, top_n=min(2, len(results)))
                    for r in validated:
                        r["sweep_name"] = name
                    all_validated.extend(validated)
                    for r in validated:
                        if (
                            best_single_result is None
                            or r["_score"] > best_single_result["_score"]
                        ):
                            best_single_result = r
                    _info(
                        "  %s: %d screen -> %d validated",
                        name,
                        len(results),
                        len(validated),
                    )
            except Exception as exc:
                _err("  Sweep %s failed: %s", name, exc)
        _info(
            "%s done in %.1fs (%d new, %d cumulative)",
            phase_label,
            time.time() - t0,
            len(all_validated) - pre,
            len(all_validated),
        )

    # Phase 1 + 2
    _sweep_phase(SINGLE_SWEEPS, "Phase 1: Single-parameter sweeps")
    _sweep_phase(SECONDARY_SWEEPS, "Phase 2: Secondary sweeps")

    # Phase 3a: Forward stepwise
    _info("Phase 3a: Forward stepwise accumulation...")
    t0 = time.time()
    if all_validated:
        stepwise_params, stepwise_score = forward_stepwise_accumulate(
            data, all_validated
        )
    else:
        stepwise_params = DEFAULTS.copy()
        stepwise_score = 0.0

    if best_single_result and stepwise_score < best_single_result["_score"]:
        _info(
            "  Stepwise %.2f < best single %.2f — using best single",
            stepwise_score,
            best_single_result["_score"],
        )
        best_params = dict(DEFAULTS)
        best_params.update(best_single_result["params"])
    else:
        _info(
            "  Stepwise %.2f >= best single %.2f — using stepwise",
            stepwise_score,
            best_single_result["_score"] if best_single_result else 0.0,
        )
        best_params = stepwise_params
    _info("Stepwise done in %.1fs", time.time() - t0)

    # Phase 3b: Adaptive multi-grid
    _info("Phase 3b: Adaptive multi-parameter grid...")
    t0 = time.time()
    try:
        grid = build_adaptive_grid(best_params)
        total_combos = 1
        for v in grid.values():
            total_combos *= len(v)
        _info("  Grid: %d combos over %d params", total_combos, len(grid))
        for k, v in grid.items():
            _info("    %s: %s", k, v)

        results = run_sweep(
            screen_data,
            "ADAPTIVE_MULTI",
            grid,
            n_workers=n_workers,
            subsample_factor=subsample,
        )
        if results:
            validated = revalidate(data, results, top_n=min(10, len(results)))
            if validated:
                validated.sort(key=lambda x: x["_score"], reverse=True)
                for r in validated:
                    r["sweep_name"] = "ADAPTIVE_MULTI"
                best_params.update(validated[0]["params"])
                all_validated.extend(validated)
                _info(
                    "  Adaptive: %d screen -> %d validated, best %.2f",
                    len(results),
                    len(validated),
                    validated[0]["_score"],
                )
    except Exception as exc:
        _err("  Adaptive multi-grid failed: %s", exc)
    _info("Adaptive multi-grid done in %.1fs", time.time() - t0)

    # Phase 4: Walk-forward
    wf_result = None
    if not skip_oos:
        _info("Phase 4: Walk-forward validation...")
        t0 = time.time()
        try:
            wf_result = run_walk_forward(data, best_params)
            avg_deg = wf_result.get("avg_degradation", float("inf"))
            consistent = wf_result.get("consistent", False)
            if consistent and avg_deg < 0.3:
                verdict = "PASS"
            elif consistent and avg_deg < 0.5:
                verdict = "CAUTION"
            else:
                verdict = "FAIL"
            _info(
                "Walk-forward: avg_degradation=%.1f%% consistent=%s [%s]",
                avg_deg * 100,
                consistent,
                verdict,
            )
        except Exception as exc:
            _err("  Walk-forward failed: %s", exc)
        _info("Walk-forward done in %.1fs", time.time() - t0)

    # Attach _ret_dd for DB persistence compatibility
    for r in all_validated:
        dd = r.get("max_drawdown_pct", 0)
        r["_ret_dd"] = r.get("total_return_pct", 0) / max(dd, 0.01)

    return best_params, all_validated, wf_result
