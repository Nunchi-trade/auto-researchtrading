from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.models import (
    EquityPoint,
    SignalEntry,
    StrategyMetrics,
    WalkForwardSummary,
    WalkForwardWindow,
)
from backend.services import backtest_cache
from backend.services.signals import recent_signals
from upbit_mtf_strategy import DEFAULT_MTF_PARAMS
from upbit_prepare import INITIAL_CAPITAL
from upbit_strategy import DEFAULT_STRATEGY_PARAMS

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

STRATEGY_INDEX = {
    "mtf": {"display_name": "Upbit MTF Strategy", "active": True},
    "spot": {"display_name": "Upbit Spot Strategy", "active": True},
    "hyperliquid": {"display_name": "Hyperliquid Strategy", "active": False},
}


@router.get("")
def list_strategies():
    return [{"id": sid, **meta} for sid, meta in STRATEGY_INDEX.items()]


@router.get("/{strategy_id}/metrics", response_model=StrategyMetrics)
def get_metrics(strategy_id: str):
    if strategy_id == "mtf":
        bt = backtest_cache.get_mtf_backtest()
        full = bt["metrics"]["full"]
        test = bt["metrics"]["test"]
        return StrategyMetrics(
            full_excess_return_pct=full["excess_return_pct"],
            test_excess_return_pct=test["excess_return_pct"],
            full_max_drawdown_pct=full["drawdown_pct"],
            test_max_drawdown_pct=test["drawdown_pct"],
            sharpe=full["sharpe"],
            win_rate_pct=0.0,
            profit_factor=0.0,
            num_trades=full["trades"],
        )
    if strategy_id == "spot":
        bt = backtest_cache.get_spot_backtest("val")
        return StrategyMetrics(
            full_excess_return_pct=bt["total_return_pct"],
            test_excess_return_pct=bt["total_return_pct"],
            full_max_drawdown_pct=bt["max_drawdown_pct"],
            test_max_drawdown_pct=bt["max_drawdown_pct"],
            sharpe=bt["sharpe"],
            win_rate_pct=bt["win_rate_pct"],
            profit_factor=bt["profit_factor"],
            num_trades=bt["num_trades"],
        )
    raise HTTPException(status_code=404, detail=f"unknown strategy: {strategy_id}")


@router.get("/{strategy_id}/equity", response_model=list[EquityPoint])
def get_equity(strategy_id: str, max_points: int = Query(1000, ge=10, le=10000)):
    if strategy_id != "spot":
        raise HTTPException(status_code=404, detail="equity curve only cached for spot")
    bt = backtest_cache.get_spot_backtest("val")
    curve = bt["equity_curve"]
    if len(curve) > max_points:
        step = len(curve) // max_points
        curve = curve[::step]
    return [EquityPoint(timestamp=i, equity=float(v)) for i, v in enumerate(curve)]


@router.get("/{strategy_id}/signals", response_model=list[SignalEntry])
def get_signals(strategy_id: str, limit: int = Query(20, ge=1, le=500)):
    if strategy_id != "spot":
        raise HTTPException(status_code=404, detail="signals only cached for spot")
    bt = backtest_cache.get_spot_backtest("val")
    return recent_signals(
        trade_log=bt["trade_log"],
        strategy="spot",
        equity_curve=bt["equity_curve"],
        initial_capital=INITIAL_CAPITAL,
        limit=limit,
    )


@router.get("/{strategy_id}/walkforward", response_model=list[WalkForwardSummary])
def get_walkforward(strategy_id: str):
    if strategy_id != "mtf":
        raise HTTPException(status_code=404, detail="walk-forward only available for mtf")

    out: list[WalkForwardSummary] = []
    for label, test_bars in [("180d", 4320), ("1y", 8760)]:
        wf = backtest_cache.get_mtf_walkforward(
            label=label, train_bars=17520, test_bars=test_bars, step_bars=test_bars,
        )
        agg = wf["aggregate"]
        windows = [
            WalkForwardWindow(
                index=w["index"],
                test_excess_return_pct=w["test_metrics"]["excess_return_pct"],
                test_drawdown_pct=w["test_metrics"]["drawdown_pct"],
                train_excess_return_pct=w["train_metrics"]["excess_return_pct"],
            )
            for w in wf["windows"]
        ]
        out.append(WalkForwardSummary(
            label=label,
            num_windows=agg["num_windows"],
            mean_test_excess_pct=agg["mean_test_excess_return_pct"],
            min_test_excess_pct=agg["min_test_excess_return_pct"],
            max_test_drawdown_pct=agg["max_test_drawdown_pct"],
            positive_ratio=agg["positive_test_window_ratio"],
            windows=windows,
        ))
    return out


@router.get("/{strategy_id}/parameters")
def get_parameters(strategy_id: str):
    if strategy_id == "mtf":
        return DEFAULT_MTF_PARAMS
    if strategy_id == "spot":
        return DEFAULT_STRATEGY_PARAMS
    raise HTTPException(status_code=404, detail=f"unknown strategy: {strategy_id}")
