from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StrategyId = Literal["mtf", "spot", "hyperliquid"]
StrategyState = Literal["flat", "reduced_high", "full_long", "holding", "inactive"]
SignalAction = Literal["buy", "sell", "reduce", "cancel"]


class StrategyMetrics(BaseModel):
    full_excess_return_pct: float
    test_excess_return_pct: float
    full_max_drawdown_pct: float
    test_max_drawdown_pct: float
    sharpe: float
    win_rate_pct: float
    profit_factor: float
    num_trades: int


class EquityPoint(BaseModel):
    timestamp: int
    equity: float
    buy_hold: float | None = None


class SignalEntry(BaseModel):
    timestamp: int
    action: SignalAction
    symbol: str
    price: float
    target_fraction: float
    state_from: str | None = None
    state_to: str | None = None
    strategy: StrategyId
    pnl_pct: float | None = None


class WalkForwardWindow(BaseModel):
    index: int
    test_excess_return_pct: float
    test_drawdown_pct: float
    train_excess_return_pct: float


class WalkForwardSummary(BaseModel):
    label: str
    num_windows: int
    mean_test_excess_pct: float
    min_test_excess_pct: float
    max_test_drawdown_pct: float
    positive_ratio: float
    windows: list[WalkForwardWindow]


class StrategyCard(BaseModel):
    id: StrategyId
    display_name: str
    state: StrategyState
    target_fraction: float
    macro_strength: float | None = None
    micro_strength: float | None = None
    equity_value: float
    pnl_today_pct: float
    last_signal_action: SignalAction | None = None
    last_signal_ts: int | None = None


class PortfolioKPI(BaseModel):
    """Per-strategy P&L is shown separately rather than combined."""
    total_equity_by_strategy: dict[StrategyId, float]
    pnl_today_by_strategy: dict[StrategyId, float]
    max_drawdown_by_strategy: dict[StrategyId, float]
    active_count: int
    total_count: int


class DashboardResponse(BaseModel):
    kpi: PortfolioKPI
    strategies: list[StrategyCard]
    recent_signals: list[SignalEntry]
    performance_summary: list[StrategyMetrics]
    equity_curve_preview: list[EquityPoint] = Field(default_factory=list)


class ParamCandidate(BaseModel):
    rank: int
    objective_score: float
    params: dict
    full_excess_return_pct: float
    test_excess_return_pct: float
    max_drawdown_pct: float
    num_trades: int


class ParamSearchRun(BaseModel):
    run_id: str
    path: str
    num_candidates: int
    best_objective: float
    updated_ts: int


class LivePosition(BaseModel):
    strategy: StrategyId
    state: StrategyState
    symbol: str
    size_krw: float
    size_coin: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl_krw: float
    unrealized_pnl_pct: float
    time_in_position_seconds: int


class LiveOrder(BaseModel):
    timestamp: int
    action: SignalAction
    symbol: str
    size_coin: float
    price: float
    fee_krw: float
    status: Literal["filled", "partial", "rejected", "pending"]


class LiveSnapshot(BaseModel):
    ticker: dict
    position: LivePosition | None
    recent_orders: list[LiveOrder]
    system_status: dict[str, str]
