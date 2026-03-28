from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
from enum import Enum


class TradeSide(Enum):
    LONG = "long"
    SHORT = "short"
    CLOSE = "close"


class RiskEventType(Enum):
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    VOLATILITY_CIRCUIT_BREAKER = "volatility_circuit_breaker"
    POSITION_LIMIT = "position_limit"
    MANUAL_KILL_SWITCH = "manual_kill_switch"
    EMERGENCY_EXIT = "emergency_exit"
    STOP_TRIGGERED = "stop_triggered"


@dataclass
class Trade:
    id: Optional[int]
    timestamp: datetime
    symbol: str
    side: str
    size: float
    price: float
    fee: float
    pnl: Optional[float]
    strategy_signal: Optional[str] = None
    order_id: Optional[str] = None


@dataclass
class Position:
    id: Optional[int]
    symbol: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    side: str
    last_updated: datetime


@dataclass
class SignalRecord:
    id: Optional[int]
    timestamp: datetime
    symbol: str
    signal_type: str
    target_position: float
    current_position: float
    executed: bool


@dataclass
class RiskEvent:
    id: Optional[int]
    timestamp: datetime
    event_type: str
    details: str
    action_taken: Optional[str] = None


@dataclass
class ParamSnapshot:
    id: Optional[int]
    run_date: datetime
    sweep_name: str
    sharpe: float
    total_return_pct: float
    max_drawdown_pct: float
    profit_factor: float
    win_rate_pct: float
    num_trades: int
    ret_dd_ratio: float
    is_best: bool
    previous_snapshot_id: Optional[int] = None
    params: Optional[Dict[str, float]] = None


@dataclass
class ParamValue:
    id: Optional[int]
    snapshot_id: int
    param_name: str
    param_value: float
