from pathlib import Path

import upbit_mtf_research
from upbit_mtf_research import compute_full_period_excess_score, search_parameter_grid


def test_full_period_excess_score_rejects_drawdown_above_20pct():
    metrics = {
        "full": {
            "strategy_return_pct": 700.0,
            "buy_hold_return_pct": 600.0,
            "excess_return_pct": 100.0,
            "drawdown_pct": 24.0,
            "trades": 40,
        },
        "test": {
            "strategy_return_pct": 40.0,
            "buy_hold_return_pct": 10.0,
            "excess_return_pct": 30.0,
            "drawdown_pct": 8.0,
            "trades": 8,
        },
    }

    assert compute_full_period_excess_score(metrics) == -9999.0


def test_full_period_excess_score_prefers_higher_excess_with_same_risk():
    slower = {
        "full": {
            "strategy_return_pct": 900.0,
            "buy_hold_return_pct": 850.0,
            "excess_return_pct": 50.0,
            "drawdown_pct": 14.0,
            "trades": 50,
        },
        "test": {
            "strategy_return_pct": 25.0,
            "buy_hold_return_pct": 15.0,
            "excess_return_pct": 10.0,
            "drawdown_pct": 6.0,
            "trades": 12,
        },
    }
    stronger = {
        "full": {
            "strategy_return_pct": 1050.0,
            "buy_hold_return_pct": 850.0,
            "excess_return_pct": 200.0,
            "drawdown_pct": 14.0,
            "trades": 50,
        },
        "test": {
            "strategy_return_pct": 40.0,
            "buy_hold_return_pct": 15.0,
            "excess_return_pct": 25.0,
            "drawdown_pct": 6.0,
            "trades": 12,
        },
    }

    assert compute_full_period_excess_score(stronger) > compute_full_period_excess_score(slower)


def test_full_period_excess_score_rejects_drawdown_above_15pct_by_default():
    metrics = {
        "full": {
            "strategy_return_pct": 700.0,
            "buy_hold_return_pct": 600.0,
            "excess_return_pct": 100.0,
            "drawdown_pct": 15.5,
            "trades": 40,
        },
        "test": {
            "strategy_return_pct": 40.0,
            "buy_hold_return_pct": 10.0,
            "excess_return_pct": 30.0,
            "drawdown_pct": 8.0,
            "trades": 8,
        },
    }

    assert compute_full_period_excess_score(metrics) == -9999.0


def test_search_parameter_grid_resume_skips_existing_results(tmp_path, monkeypatch):
    grid = {"FULL_LONG_PCT": [0.9, 1.0], "REDUCED_PCT": [0.35]}
    results_path = tmp_path / "mtf-results.jsonl"
    existing_line = (
        '{"params":{"FULL_LONG_PCT":0.9,"REDUCED_PCT":0.35},'
        '"objective_score":1.0,'
        '"metrics":{"full":{"excess_return_pct":1.0},"test":{"excess_return_pct":0.5}}}'
    )
    results_path.write_text(existing_line + "\n", encoding="utf-8")

    calls: list[dict] = []

    def fake_evaluate(params, datasets, *, max_drawdown_pct):
        calls.append(params.copy())
        return {
            "params": params.copy(),
            "objective_score": 5.0,
            "metrics": {
                "full": {"excess_return_pct": 5.0, "drawdown_pct": 10.0, "trades": 10},
                "test": {"excess_return_pct": 2.0, "drawdown_pct": 5.0, "trades": 4},
            },
        }

    monkeypatch.setattr(upbit_mtf_research, "evaluate_parameter_set", fake_evaluate)

    results = search_parameter_grid(
        grid=grid,
        datasets={},
        results_path=results_path,
        progress_every=0,
    )

    assert calls == [{"FULL_LONG_PCT": 1.0, "REDUCED_PCT": 0.35}]
    assert len(results) == 2
    persisted_lines = results_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(persisted_lines) == 2


def test_search_parameter_grid_max_evals_limits_new_combos(monkeypatch):
    grid = {"FULL_LONG_PCT": [0.9, 1.0], "REDUCED_PCT": [0.35, 0.55]}
    calls: list[dict] = []

    def fake_evaluate(params, datasets, *, max_drawdown_pct):
        calls.append(params.copy())
        return {
            "params": params.copy(),
            "objective_score": float(len(calls)),
            "metrics": {
                "full": {"excess_return_pct": float(len(calls)), "drawdown_pct": 10.0, "trades": 10},
                "test": {"excess_return_pct": 1.0, "drawdown_pct": 5.0, "trades": 4},
            },
        }

    monkeypatch.setattr(upbit_mtf_research, "evaluate_parameter_set", fake_evaluate)

    results = search_parameter_grid(
        grid=grid,
        datasets={},
        max_evals=1,
        progress_every=0,
    )

    assert len(calls) == 1
    assert len(results) == 1


def test_load_search_results_ignores_truncated_last_line(tmp_path):
    results_path = tmp_path / "mtf-results.jsonl"
    results_path.write_text(
        "\n".join(
            [
                '{"params":{"FULL_LONG_PCT":0.9},"objective_score":1.0,"metrics":{"full":{"excess_return_pct":1.0},"test":{"excess_return_pct":0.5}}}',
                '{"params":{"FULL_LONG_PCT":1.0},"objective_score":',
            ]
        ),
        encoding="utf-8",
    )

    results = upbit_mtf_research.load_search_results(results_path)

    assert len(results) == 1
    assert results[0]["params"] == {"FULL_LONG_PCT": 0.9}


def test_results_path_expands_user_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = {
        "params": {"FULL_LONG_PCT": 0.9},
        "objective_score": 1.0,
        "metrics": {
            "full": {"excess_return_pct": 1.0, "drawdown_pct": 10.0, "trades": 1},
            "test": {"excess_return_pct": 0.5, "drawdown_pct": 5.0, "trades": 1},
        },
    }

    upbit_mtf_research.append_search_result("~/mtf-results.jsonl", result)

    saved = tmp_path / "mtf-results.jsonl"
    assert saved.exists()
    loaded = upbit_mtf_research.load_search_results("~/mtf-results.jsonl")
    assert loaded[0]["params"] == {"FULL_LONG_PCT": 0.9}
