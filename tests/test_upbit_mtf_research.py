from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import upbit_mtf_research
from upbit_mtf_research import (
    build_walkforward_windows,
    compute_full_period_excess_score,
    evaluate_walkforward_parameter_set,
    search_parameter_grid,
)


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


def test_build_walkforward_windows_advances_by_step():
    base_df = pd.DataFrame({
        "timestamp": list(range(10)),
        "close": [100.0 + i for i in range(10)],
    })

    windows = build_walkforward_windows(base_df, train_bars=4, test_bars=2, step_bars=2)

    assert [window["train_start_ts"] for window in windows] == [0, 2, 4]
    assert [window["test_start_ts"] for window in windows] == [4, 6, 8]
    assert [window["test_end_ts"] for window in windows] == [5, 7, 9]


def test_evaluate_walkforward_parameter_set_aggregates_test_windows(monkeypatch):
    base_df = pd.DataFrame(
        {
            "timestamp": list(range(8)),
            "open": [100.0] * 8,
            "high": [101.0] * 8,
            "low": [99.0] * 8,
            "close": [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0],
            "volume": [1.0] * 8,
        }
    )
    datasets = {
        "interval_data": {60: {"KRW-BTC": base_df}},
        "base_full": {"KRW-BTC": base_df},
    }
    returns = iter([10.0, 6.0, 20.0, 8.0])
    drawdowns = iter([4.0, 2.0, 5.0, 3.0])
    trades = iter([100, 40, 120, 50])

    def fake_run(strategy, data):
        return SimpleNamespace(
            total_return_pct=next(returns),
            max_drawdown_pct=next(drawdowns),
            num_trades=next(trades),
            sharpe=1.0,
        )

    monkeypatch.setattr(upbit_mtf_research, "run_upbit_backtest", fake_run)
    monkeypatch.setattr(upbit_mtf_research, "compute_buy_hold_return_pct", lambda data: 5.0)

    result = evaluate_walkforward_parameter_set(
        params={"FULL_LONG_PCT": 0.9},
        datasets=datasets,
        train_bars=4,
        test_bars=2,
        step_bars=2,
        base_interval=60,
    )

    assert result["aggregate"]["num_windows"] == 2
    assert result["aggregate"]["mean_test_excess_return_pct"] == 2.0
    assert result["aggregate"]["min_test_excess_return_pct"] == 1.0
    assert result["aggregate"]["max_test_drawdown_pct"] == 3.0
    assert result["aggregate"]["positive_test_window_ratio"] == 1.0
    assert [window["test_metrics"]["excess_return_pct"] for window in result["windows"]] == [1.0, 3.0]


def test_evaluate_walkforward_parameter_set_passes_causal_feature_store_ranges(monkeypatch):
    base_df = pd.DataFrame(
        {
            "timestamp": list(range(6)),
            "open": [100.0] * 6,
            "high": [101.0] * 6,
            "low": [99.0] * 6,
            "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
            "volume": [1.0] * 6,
        }
    )
    datasets = {
        "interval_data": {
            60: {"KRW-BTC": base_df},
            240: {"KRW-BTC": base_df},
        },
        "base_full": {"KRW-BTC": base_df},
    }
    strategy_interval_data: list[dict] = []
    feature_store_max_timestamps: list[int] = []

    class FakeStrategy:
        def __init__(self, interval_data, params=None, feature_store=None):
            strategy_interval_data.append(interval_data)
            feature_store_max_timestamps.append(
                int(feature_store[60]["KRW-BTC"]["timestamp"].max())
            )

    def fake_run(strategy, data):
        return SimpleNamespace(
            total_return_pct=10.0,
            max_drawdown_pct=2.0,
            num_trades=10,
            sharpe=1.0,
        )

    monkeypatch.setattr(upbit_mtf_research, "MultiTimeframeStrategy", FakeStrategy)
    monkeypatch.setattr(upbit_mtf_research, "run_upbit_backtest", fake_run)
    monkeypatch.setattr(upbit_mtf_research, "compute_buy_hold_return_pct", lambda data: 5.0)

    evaluate_walkforward_parameter_set(
        params={"FULL_LONG_PCT": 0.9},
        datasets=datasets,
        train_bars=4,
        test_bars=2,
        step_bars=2,
    )

    assert strategy_interval_data == [{}, {}]
    assert feature_store_max_timestamps == [3, 5]
