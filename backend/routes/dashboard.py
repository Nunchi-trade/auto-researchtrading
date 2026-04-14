from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.models import (
    DashboardResponse,
    PortfolioKPI,
    SignalEntry,
    StrategyCard,
    StrategyMetrics,
)
from backend.services import backtest_cache
from backend.services.signals import recent_signals
from upbit_mtf_strategy import FULL_LONG_PCT, REDUCED_PCT
from upbit_prepare import INITIAL_CAPITAL

router = APIRouter(prefix="/api", tags=["dashboard"])


def _mtf_card(bt: dict) -> StrategyCard:
    test = bt["metrics"]["test"]
    return StrategyCard(
        id="mtf",
        display_name="Upbit MTF Strategy",
        state="full_long",
        target_fraction=FULL_LONG_PCT,
        macro_strength=0.73,
        micro_strength=0.67,
        equity_value=INITIAL_CAPITAL * (1.0 + test["strategy_return_pct"] / 100.0) * FULL_LONG_PCT,
        pnl_today_pct=0.0,
        last_signal_action="buy",
    )


def _spot_card(bt: dict) -> StrategyCard:
    return StrategyCard(
        id="spot",
        display_name="Upbit Spot Strategy",
        state="holding",
        target_fraction=0.45,
        equity_value=INITIAL_CAPITAL * (1.0 + bt["total_return_pct"] / 100.0) * 0.45,
        pnl_today_pct=0.0,
        last_signal_action="buy",
    )


def _hyperliquid_card() -> StrategyCard:
    return StrategyCard(
        id="hyperliquid",
        display_name="Hyperliquid Strategy",
        state="inactive",
        target_fraction=0.0,
        equity_value=0.0,
        pnl_today_pct=0.0,
    )


def _mtf_metrics(bt: dict) -> StrategyMetrics:
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


def _spot_metrics(bt: dict) -> StrategyMetrics:
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


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard():
    try:
        mtf_bt = backtest_cache.get_mtf_backtest()
        spot_bt = backtest_cache.get_spot_backtest("val")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"backtest unavailable: {exc}") from exc

    mtf_card = _mtf_card(mtf_bt)
    spot_card = _spot_card(spot_bt)
    hl_card = _hyperliquid_card()

    mtf_metrics = _mtf_metrics(mtf_bt)
    spot_metrics = _spot_metrics(spot_bt)

    spot_signals: list[SignalEntry] = recent_signals(
        trade_log=spot_bt["trade_log"],
        strategy="spot",
        equity_curve=spot_bt["equity_curve"],
        initial_capital=INITIAL_CAPITAL,
        limit=10,
    )

    kpi = PortfolioKPI(
        total_equity_by_strategy={
            "mtf": mtf_card.equity_value,
            "spot": spot_card.equity_value,
            "hyperliquid": hl_card.equity_value,
        },
        pnl_today_by_strategy={
            "mtf": mtf_card.pnl_today_pct,
            "spot": spot_card.pnl_today_pct,
            "hyperliquid": hl_card.pnl_today_pct,
        },
        max_drawdown_by_strategy={
            "mtf": mtf_metrics.full_max_drawdown_pct,
            "spot": spot_metrics.full_max_drawdown_pct,
            "hyperliquid": 0.0,
        },
        active_count=2,
        total_count=3,
    )

    return DashboardResponse(
        kpi=kpi,
        strategies=[mtf_card, spot_card, hl_card],
        recent_signals=spot_signals,
        performance_summary=[mtf_metrics, spot_metrics],
    )
