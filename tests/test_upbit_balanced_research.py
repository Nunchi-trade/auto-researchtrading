from upbit_balanced_research import (
    compute_balanced_score,
    compute_return_risk_score,
    iter_parameter_grid,
)


def test_balanced_score_prefers_even_profiles():
    lopsided = {"train": 1.0, "val": 4.0, "test": 0.5}
    balanced = {"train": 1.2, "val": 2.0, "test": 1.1}

    assert compute_balanced_score(balanced) > compute_balanced_score(lopsided)


def test_iter_parameter_grid_emits_override_dicts():
    grid = {
        "BASE_POSITION_PCT": [0.45, 0.60],
        "COOLDOWN_BARS": [24, 36],
    }

    combos = list(iter_parameter_grid(grid))

    assert combos == [
        {"BASE_POSITION_PCT": 0.45, "COOLDOWN_BARS": 24},
        {"BASE_POSITION_PCT": 0.45, "COOLDOWN_BARS": 36},
        {"BASE_POSITION_PCT": 0.60, "COOLDOWN_BARS": 24},
        {"BASE_POSITION_PCT": 0.60, "COOLDOWN_BARS": 36},
    ]


def test_return_risk_score_rejects_high_drawdown():
    split_metrics = {
        "train": {"return_pct": 80.0, "drawdown_pct": 8.0},
        "val": {"return_pct": 30.0, "drawdown_pct": 4.0},
        "test": {"return_pct": 12.0, "drawdown_pct": 14.0},
    }

    assert compute_return_risk_score(split_metrics) == -999.0


def test_return_risk_score_prefers_higher_return_with_controlled_drawdown():
    defensive = {
        "train": {"return_pct": 35.0, "drawdown_pct": 6.0},
        "val": {"return_pct": 18.0, "drawdown_pct": 3.0},
        "test": {"return_pct": 10.0, "drawdown_pct": 4.0},
    }
    productive = {
        "train": {"return_pct": 80.0, "drawdown_pct": 8.0},
        "val": {"return_pct": 26.0, "drawdown_pct": 4.0},
        "test": {"return_pct": 16.0, "drawdown_pct": 5.0},
    }

    assert compute_return_risk_score(productive) > compute_return_risk_score(defensive)
