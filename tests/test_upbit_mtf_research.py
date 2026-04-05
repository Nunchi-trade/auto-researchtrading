from upbit_mtf_research import compute_full_period_excess_score


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
