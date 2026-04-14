import itertools
from typing import Iterator

import numpy as np

from upbit_prepare import compute_upbit_score, load_upbit_data, run_upbit_backtest
from upbit_strategy import Strategy

DEFAULT_PARAMETER_GRID = {
    "BASE_POSITION_PCT": [0.45, 0.60, 0.75],
    "SIZE_TARGET_VOL": [0.0030, 0.0035, 0.0045],
    "MIN_POSITION_SCALE": [0.20, 0.25],
    "COOLDOWN_BARS": [24, 36],
    "MAX_HOLD_BARS": [72, 96],
    "MIN_BEAR_VOTES": [4, 5],
}

RETURN_RISK_PARAMETER_GRID = {
    "BASE_POSITION_PCT": [0.45, 0.50],
    "SIZE_TARGET_VOL": [0.0035],
    "MIN_POSITION_SCALE": [0.25],
    "COOLDOWN_BARS": [36, 48],
    "MAX_HOLD_BARS": [96, 120],
    "MIN_BEAR_VOTES": [4, 5],
    "RECENT_HIGH_BUFFER": [0.995, 0.997],
    "STOCH_EXIT_THRESHOLD": [40.0, 45.0],
}

BALANCED_MEAN_WEIGHT = 0.35
BALANCED_GAP_WEIGHT = 0.15
RETURN_RISK_RETURN_WEIGHT = 0.02
RETURN_RISK_SPREAD_WEIGHT = 0.01
RETURN_RISK_DRAWDOWN_CUTOFF = 12.0


def iter_parameter_grid(grid: dict[str, list]) -> Iterator[dict]:
    keys = list(grid.keys())
    for values in itertools.product(*(grid[key] for key in keys)):
        yield dict(zip(keys, values))


def compute_balanced_score(
    split_scores: dict[str, float],
    *,
    mean_weight: float = BALANCED_MEAN_WEIGHT,
    gap_weight: float = BALANCED_GAP_WEIGHT,
) -> float:
    values = np.array(list(split_scores.values()), dtype=float)
    worst_split_score = float(values.min())
    mean_score = float(values.mean())
    score_gap = float(values.max() - values.min())
    return worst_split_score + mean_weight * mean_score - gap_weight * score_gap


def compute_return_risk_score(
    split_metrics: dict[str, dict],
    *,
    drawdown_cutoff: float = RETURN_RISK_DRAWDOWN_CUTOFF,
    return_weight: float = RETURN_RISK_RETURN_WEIGHT,
    spread_weight: float = RETURN_RISK_SPREAD_WEIGHT,
) -> float:
    drawdowns = np.array([metrics["drawdown_pct"] for metrics in split_metrics.values()], dtype=float)
    returns = np.array([metrics["return_pct"] for metrics in split_metrics.values()], dtype=float)

    if float(drawdowns.max()) > drawdown_cutoff:
        return -999.0
    if float(split_metrics["test"]["return_pct"]) <= 0.0:
        return -999.0

    return_to_drawdown = returns / np.maximum(drawdowns, 1.0)
    worst_ratio = float(return_to_drawdown.min())
    mean_return = float(returns.mean())
    return_spread = float(returns.max() - returns.min())
    return worst_ratio + return_weight * mean_return - spread_weight * return_spread


def _grid_for_objective(objective: str) -> dict[str, list]:
    if objective == "balanced":
        return DEFAULT_PARAMETER_GRID
    if objective == "return_risk":
        return RETURN_RISK_PARAMETER_GRID
    raise ValueError(f"unsupported objective: {objective}")


def _score_result(
    objective: str,
    split_scores: dict[str, float],
    split_metrics: dict[str, dict],
) -> float:
    if objective == "balanced":
        return compute_balanced_score(split_scores)
    if objective == "return_risk":
        return compute_return_risk_score(split_metrics)
    raise ValueError(f"unsupported objective: {objective}")


def load_split_datasets(interval_minutes: int = 60) -> dict[str, dict]:
    return {
        split: load_upbit_data(split, interval_minutes=interval_minutes)
        for split in ("train", "val", "test")
    }


def evaluate_parameter_set(
    params: dict,
    datasets: dict[str, dict],
    *,
    objective: str = "balanced",
) -> dict:
    split_scores: dict[str, float] = {}
    split_metrics: dict[str, dict] = {}

    for split, data in datasets.items():
        result = run_upbit_backtest(Strategy(params=params), data)
        score = compute_upbit_score(result)
        split_scores[split] = score
        split_metrics[split] = {
            "score": score,
            "return_pct": result.total_return_pct,
            "drawdown_pct": result.max_drawdown_pct,
            "trades": result.num_trades,
        }

    balanced_score = compute_balanced_score(split_scores)
    return_risk_score = compute_return_risk_score(split_metrics)
    objective_score = _score_result(objective, split_scores, split_metrics)

    return {
        "params": params.copy(),
        "objective": objective,
        "objective_score": objective_score,
        "balanced_score": balanced_score,
        "return_risk_score": return_risk_score,
        "split_scores": split_scores,
        "metrics": split_metrics,
    }


def search_parameter_grid(
    *,
    grid: dict[str, list] | None = None,
    datasets: dict[str, dict] | None = None,
    interval_minutes: int = 60,
    progress_every: int = 25,
    objective: str = "balanced",
) -> list[dict]:
    parameter_grid = grid or _grid_for_objective(objective)
    split_datasets = datasets or load_split_datasets(interval_minutes=interval_minutes)
    results = []

    for index, params in enumerate(iter_parameter_grid(parameter_grid), start=1):
        results.append(evaluate_parameter_set(params, split_datasets, objective=objective))
        if progress_every and index % progress_every == 0:
            print(f"[{index}] combos evaluated")

    results.sort(
        key=lambda item: (
            item["objective_score"],
            min(item["split_scores"].values()),
            np.mean(list(item["split_scores"].values())),
        ),
        reverse=True,
    )
    return results
