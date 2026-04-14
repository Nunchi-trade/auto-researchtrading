from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from upbit_mtf_research import (
    evaluate_parameter_set as evaluate_mtf_params,
    evaluate_walkforward_parameter_set,
    load_search_datasets,
)
from upbit_mtf_strategy import DEFAULT_MTF_PARAMS
from upbit_prepare import (
    UpbitBacktestResult,
    compute_upbit_score,
    load_upbit_data,
    run_upbit_backtest,
)
from upbit_strategy import DEFAULT_STRATEGY_PARAMS, Strategy as SpotStrategy

CACHE_DIR = Path.home() / ".cache" / "autotrader_upbit" / "api"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_mtf_datasets_memo: dict | None = None


def _params_hash(strategy_id: str, params: dict) -> str:
    payload = json.dumps({"id": strategy_id, "params": params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _cache_path(strategy_id: str, params: dict) -> Path:
    return CACHE_DIR / f"{strategy_id}_{_params_hash(strategy_id, params)}.json"


def _result_to_dict(result: UpbitBacktestResult, score: float) -> dict:
    payload = asdict(result)
    payload["score"] = score
    return payload


def get_mtf_datasets():
    global _mtf_datasets_memo
    if _mtf_datasets_memo is None:
        _mtf_datasets_memo = load_search_datasets()
    return _mtf_datasets_memo


def get_mtf_backtest(params: dict | None = None) -> dict:
    """Return cached MTF full-period + test-period metrics, evaluating on demand."""
    merged = {**DEFAULT_MTF_PARAMS, **(params or {})}
    path = _cache_path("mtf", merged)
    if path.exists():
        return json.loads(path.read_text())

    result = evaluate_mtf_params(merged, get_mtf_datasets())
    path.write_text(json.dumps(result, default=float))
    return result


def get_spot_backtest(split: str = "val", params: dict | None = None) -> dict:
    """Return cached Spot backtest for a single split."""
    merged = {**DEFAULT_STRATEGY_PARAMS, **(params or {})}
    cache_key = {"split": split, **merged}
    path = _cache_path(f"spot_{split}", cache_key)
    if path.exists():
        return json.loads(path.read_text())

    data = load_upbit_data(split, interval_minutes=60)
    result = run_upbit_backtest(SpotStrategy(params=merged), data)
    score = compute_upbit_score(result)
    payload = _result_to_dict(result, score)
    path.write_text(json.dumps(payload, default=float))
    return payload


def get_mtf_walkforward(
    label: str,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    params: dict | None = None,
) -> dict:
    """Return cached walk-forward result for a given window spec."""
    merged = {**DEFAULT_MTF_PARAMS, **(params or {})}
    cache_key = {"label": label, "train": train_bars, "test": test_bars, "step": step_bars, **merged}
    path = _cache_path(f"mtf_wf_{label}", cache_key)
    if path.exists():
        return json.loads(path.read_text())

    wf = evaluate_walkforward_parameter_set(
        merged, get_mtf_datasets(),
        train_bars=train_bars, test_bars=test_bars, step_bars=step_bars,
    )
    path.write_text(json.dumps(wf, default=float))
    return wf


def invalidate_cache(strategy_id: str | None = None) -> int:
    """Remove cached results. Returns count of removed files."""
    if strategy_id is None:
        files = list(CACHE_DIR.glob("*.json"))
    else:
        files = list(CACHE_DIR.glob(f"{strategy_id}*.json"))
    for f in files:
        f.unlink()
    return len(files)
