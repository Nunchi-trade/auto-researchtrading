from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from upbit_mtf_strategy import MultiTimeframeStrategy, build_feature_store
from upbit_prepare import load_upbit_data, run_upbit_backtest

DEFAULT_MTF_PARAMETER_GRID = {
    "FULL_LONG_PCT": [0.90, 1.00],
    "REDUCED_PCT": [0.35, 0.55],
    "MACRO_FULL_THRESHOLD": [0.62, 0.70],
    "MICRO_FULL_THRESHOLD": [0.50, 0.60],
    "MAX_MACRO_DRAWDOWN": [0.16, 0.20],
}

COARSE_MTF_PARAMETER_GRID = {
    "FULL_LONG_PCT": [0.90, 1.00],
    "REDUCED_PCT": [0.35, 0.55],
    "MACRO_FULL_THRESHOLD": [0.62, 0.70],
    "MICRO_FULL_THRESHOLD": [0.50],
    "MAX_MACRO_DRAWDOWN": [0.16],
}

FULL_PERIOD_MAX_DRAWDOWN_PCT = 15.0
TEST_EXCESS_WEIGHT = 0.35
TRADE_PENALTY_WEIGHT = 0.02


def _slice_symbol_frames(data: dict[str, pd.DataFrame], start_ts: int, end_ts: int) -> dict[str, pd.DataFrame]:
    sliced: dict[str, pd.DataFrame] = {}
    for symbol, df in data.items():
        window = df[(df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)].reset_index(drop=True)
        if not window.empty:
            sliced[symbol] = window
    return sliced


def _slice_interval_frames(
    interval_data: dict[int, dict[str, pd.DataFrame]],
    start_ts: int,
    end_ts: int,
) -> dict[int, dict[str, pd.DataFrame]]:
    sliced: dict[int, dict[str, pd.DataFrame]] = {}
    for interval_minutes, symbol_frames in interval_data.items():
        interval_slice = _slice_symbol_frames(symbol_frames, start_ts, end_ts)
        if interval_slice:
            sliced[interval_minutes] = interval_slice
    return sliced


def _slice_feature_store(
    feature_store: dict[int, dict[str, dict[str, np.ndarray]]],
    start_ts: int,
    end_ts: int,
) -> dict[int, dict[str, dict[str, np.ndarray]]]:
    sliced: dict[int, dict[str, dict[str, np.ndarray]]] = {}
    for interval_minutes, symbol_store in feature_store.items():
        interval_slice: dict[str, dict[str, np.ndarray]] = {}
        for symbol, features in symbol_store.items():
            timestamps = features["timestamp"]
            mask = (timestamps >= start_ts) & (timestamps <= end_ts)
            if not np.any(mask):
                continue
            interval_slice[symbol] = {
                name: values[mask]
                for name, values in features.items()
            }
        if interval_slice:
            sliced[interval_minutes] = interval_slice
    return sliced


def build_walkforward_windows(
    base_df: pd.DataFrame,
    *,
    train_bars: int,
    test_bars: int,
    step_bars: int | None = None,
) -> list[dict[str, int]]:
    if train_bars <= 0 or test_bars <= 0:
        raise ValueError("train_bars and test_bars must be positive")

    step = step_bars or test_bars
    if step <= 0:
        raise ValueError("step_bars must be positive")

    windows: list[dict[str, int]] = []
    total_rows = len(base_df)
    for test_start_index in range(train_bars, total_rows - test_bars + 1, step):
        train_start_index = test_start_index - train_bars
        train_end_index = test_start_index - 1
        test_end_index = test_start_index + test_bars - 1
        windows.append(
            {
                "train_start_ts": int(base_df["timestamp"].iloc[train_start_index]),
                "train_end_ts": int(base_df["timestamp"].iloc[train_end_index]),
                "test_start_ts": int(base_df["timestamp"].iloc[test_start_index]),
                "test_end_ts": int(base_df["timestamp"].iloc[test_end_index]),
                "train_bars": train_bars,
                "test_bars": test_bars,
            }
        )
    return windows


def iter_parameter_grid(grid: dict[str, list]) -> Iterator[dict]:
    keys = list(grid.keys())
    for values in itertools.product(*(grid[key] for key in keys)):
        yield dict(zip(keys, values))


def get_parameter_grid(preset: str = "default") -> dict[str, list]:
    presets = {
        "default": DEFAULT_MTF_PARAMETER_GRID,
        "coarse": COARSE_MTF_PARAMETER_GRID,
    }
    if preset not in presets:
        raise ValueError(f"unknown grid preset: {preset}")
    return {key: list(values) for key, values in presets[preset].items()}


def _concat_split_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
        .reset_index(drop=True)
    )


def load_full_interval_datasets(intervals: tuple[int, ...] = (10, 20, 30, 60, 240)) -> dict[int, dict[str, pd.DataFrame]]:
    split_names = ("train", "val", "test")
    full_datasets: dict[int, dict[str, pd.DataFrame]] = {}

    for interval_minutes in intervals:
        split_frames = {
            split: load_upbit_data(split, interval_minutes=interval_minutes)
            for split in split_names
        }
        symbols = sorted({symbol for data in split_frames.values() for symbol in data})
        full_datasets[interval_minutes] = {}
        for symbol in symbols:
            frames = [split_frames[split][symbol] for split in split_names if symbol in split_frames[split]]
            if frames:
                full_datasets[interval_minutes][symbol] = _concat_split_frames(frames)
    return full_datasets


def load_search_datasets(
    *,
    intervals: tuple[int, ...] = (10, 20, 30, 60, 240),
    base_interval: int = 60,
) -> dict:
    interval_data = load_full_interval_datasets(intervals=intervals)
    base_test = load_upbit_data("test", interval_minutes=base_interval)
    return {
        "interval_data": interval_data,
        "base_full": interval_data[base_interval],
        "base_test": base_test,
        "feature_store": build_feature_store(interval_data),
    }


def compute_buy_hold_return_pct(data: dict[str, pd.DataFrame]) -> float:
    if not data:
        return 0.0
    symbol = sorted(data.keys())[0]
    df = data[symbol]
    if df.empty:
        return 0.0
    first_close = float(df["close"].iloc[0])
    last_close = float(df["close"].iloc[-1])
    return (last_close / first_close - 1.0) * 100.0


def compute_full_period_excess_score(
    metrics: dict[str, dict],
    *,
    max_drawdown_pct: float = FULL_PERIOD_MAX_DRAWDOWN_PCT,
    test_excess_weight: float = TEST_EXCESS_WEIGHT,
    trade_penalty_weight: float = TRADE_PENALTY_WEIGHT,
) -> float:
    full_metrics = metrics["full"]
    if float(full_metrics["drawdown_pct"]) > max_drawdown_pct:
        return -9999.0

    return (
        float(full_metrics["excess_return_pct"])
        + test_excess_weight * float(metrics["test"]["excess_return_pct"])
        - trade_penalty_weight * float(full_metrics["trades"])
    )


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _params_key(params: dict) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def _normalize_results_path(results_path: str | Path) -> Path:
    return Path(results_path).expanduser()


def load_search_results(results_path: str | Path) -> list[dict]:
    path = _normalize_results_path(results_path)
    if not path.exists():
        return []

    results = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                # Resume files are append-only jsonl. If the process was interrupted
                # mid-write, skip the truncated tail and recover prior results.
                break
    return results


def append_search_result(results_path: str | Path, result: dict) -> None:
    path = _normalize_results_path(results_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(_json_safe(result), handle, ensure_ascii=True, sort_keys=True)
        handle.write("\n")


def _extract_metrics(result, buy_hold_return_pct: float) -> dict[str, float]:
    return {
        "strategy_return_pct": result.total_return_pct,
        "buy_hold_return_pct": buy_hold_return_pct,
        "excess_return_pct": result.total_return_pct - buy_hold_return_pct,
        "drawdown_pct": result.max_drawdown_pct,
        "trades": result.num_trades,
        "sharpe": result.sharpe,
    }


def evaluate_parameter_set(
    params: dict,
    datasets: dict,
    *,
    max_drawdown_pct: float = FULL_PERIOD_MAX_DRAWDOWN_PCT,
) -> dict:
    interval_data = datasets["interval_data"]
    feature_store = datasets["feature_store"]

    full_result = run_upbit_backtest(
        MultiTimeframeStrategy(interval_data, params=params, feature_store=feature_store),
        datasets["base_full"],
    )
    test_result = run_upbit_backtest(
        MultiTimeframeStrategy(interval_data, params=params, feature_store=feature_store),
        datasets["base_test"],
    )

    metrics = {
        "full": _extract_metrics(full_result, compute_buy_hold_return_pct(datasets["base_full"])),
        "test": _extract_metrics(test_result, compute_buy_hold_return_pct(datasets["base_test"])),
    }
    objective_score = compute_full_period_excess_score(metrics, max_drawdown_pct=max_drawdown_pct)

    return {
        "params": params.copy(),
        "objective_score": objective_score,
        "metrics": metrics,
    }


def evaluate_walkforward_parameter_set(
    params: dict,
    datasets: dict,
    *,
    train_bars: int,
    test_bars: int,
    step_bars: int | None = None,
    base_interval: int = 60,
) -> dict:
    base_full = datasets["base_full"]
    if not base_full:
        return {
            "params": params.copy(),
            "aggregate": {
                "num_windows": 0,
                "mean_test_excess_return_pct": 0.0,
                "min_test_excess_return_pct": 0.0,
                "max_test_drawdown_pct": 0.0,
                "positive_test_window_ratio": 0.0,
            },
            "windows": [],
        }
    full_feature_store = datasets.get("feature_store") or build_feature_store(datasets["interval_data"])

    symbol = sorted(base_full.keys())[0]
    windows = build_walkforward_windows(
        base_full[symbol],
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars,
    )

    window_results: list[dict] = []
    for index, window in enumerate(windows, start=1):
        train_feature_store = _slice_feature_store(
            full_feature_store,
            window["train_start_ts"],
            window["train_end_ts"],
        )
        test_feature_store = _slice_feature_store(
            full_feature_store,
            window["train_start_ts"],
            window["test_end_ts"],
        )
        train_base = _slice_symbol_frames(base_full, window["train_start_ts"], window["train_end_ts"])
        test_base = _slice_symbol_frames(base_full, window["test_start_ts"], window["test_end_ts"])

        train_result = run_upbit_backtest(
            MultiTimeframeStrategy({}, params=params, feature_store=train_feature_store),
            train_base,
        )
        test_result = run_upbit_backtest(
            MultiTimeframeStrategy({}, params=params, feature_store=test_feature_store),
            test_base,
        )

        window_results.append(
            {
                "index": index,
                **window,
                "train_metrics": _extract_metrics(train_result, compute_buy_hold_return_pct(train_base)),
                "test_metrics": _extract_metrics(test_result, compute_buy_hold_return_pct(test_base)),
            }
        )

    if not window_results:
        aggregate = {
            "num_windows": 0,
            "mean_test_excess_return_pct": 0.0,
            "min_test_excess_return_pct": 0.0,
            "max_test_drawdown_pct": 0.0,
            "positive_test_window_ratio": 0.0,
        }
    else:
        test_excess = np.array([item["test_metrics"]["excess_return_pct"] for item in window_results], dtype=float)
        test_drawdowns = np.array([item["test_metrics"]["drawdown_pct"] for item in window_results], dtype=float)
        aggregate = {
            "num_windows": len(window_results),
            "mean_test_excess_return_pct": float(test_excess.mean()),
            "min_test_excess_return_pct": float(test_excess.min()),
            "max_test_drawdown_pct": float(test_drawdowns.max()),
            "positive_test_window_ratio": float((test_excess > 0).mean()),
        }

    return {
        "params": params.copy(),
        "aggregate": aggregate,
        "windows": window_results,
    }


def search_parameter_grid(
    *,
    grid: dict[str, list] | None = None,
    grid_preset: str = "default",
    datasets: dict | None = None,
    intervals: tuple[int, ...] = (10, 20, 30, 60, 240),
    base_interval: int = 60,
    progress_every: int = 10,
    max_drawdown_pct: float = FULL_PERIOD_MAX_DRAWDOWN_PCT,
    max_evals: int | None = None,
    results_path: str | Path | None = None,
) -> list[dict]:
    parameter_grid = grid or get_parameter_grid(grid_preset)
    search_datasets = datasets or load_search_datasets(intervals=intervals, base_interval=base_interval)
    results = load_search_results(results_path) if results_path else []
    seen = {_params_key(item["params"]): item for item in results}
    evaluated_in_run = 0

    for index, params in enumerate(iter_parameter_grid(parameter_grid), start=1):
        key = _params_key(params)
        if key in seen:
            continue

        result = evaluate_parameter_set(
            params,
            search_datasets,
            max_drawdown_pct=max_drawdown_pct,
        )
        results.append(result)
        seen[key] = result
        evaluated_in_run += 1
        if results_path:
            append_search_result(results_path, result)
        if progress_every and index % progress_every == 0:
            print(f"[{index}] combos scanned, {evaluated_in_run} new combos evaluated", flush=True)
        if max_evals is not None and evaluated_in_run >= max_evals:
            break

    results.sort(
        key=lambda item: (
            item["objective_score"],
            item["metrics"]["full"]["excess_return_pct"],
            item["metrics"]["test"]["excess_return_pct"],
        ),
        reverse=True,
    )
    return results
