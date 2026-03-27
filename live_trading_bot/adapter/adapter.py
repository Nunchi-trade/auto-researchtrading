import sys
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

repo_root = Path(__file__).resolve().parent.parent.parent

if "prepare" not in sys.modules:
    _p_spec = importlib.util.spec_from_file_location(
        "prepare", repo_root / "prepare.py"
    )
    assert _p_spec is not None, f"Failed to load spec for {repo_root / 'prepare.py'}"
    assert _p_spec.loader is not None, f"No loader for {repo_root / 'prepare.py'}"
    _p_mod = importlib.util.module_from_spec(_p_spec)
    sys.modules["prepare"] = _p_mod
    _p_spec.loader.exec_module(_p_mod)
else:
    _p_mod = sys.modules["prepare"]

_s_spec = importlib.util.spec_from_file_location(
    "_bt_strategy", repo_root / "strategy.py"
)
assert _s_spec is not None, f"Failed to load spec for {repo_root / 'strategy.py'}"
assert _s_spec.loader is not None, f"No loader for {repo_root / 'strategy.py'}"
_s_mod = importlib.util.module_from_spec(_s_spec)
sys.modules["_bt_strategy"] = _s_mod
_s_spec.loader.exec_module(_s_mod)

BarData = _p_mod.BarData
PortfolioState = _p_mod.PortfolioState

from exchange.order_manager import Signal as LiveSignal
from exchange.types import Candle, AccountState, PositionSide
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)

_settings = get_settings()

if _settings.STRATEGY_MODULE == "_bt_strategy":
    BacktestStrategy = _s_mod.Strategy
else:
    _strategy_mod = importlib.import_module(_settings.STRATEGY_MODULE)
    BacktestStrategy = _strategy_mod.Strategy


class LiveStrategyAdapter:
    """Wraps the backtest Strategy for live trading.

    Conversion boundary:
    - Exchange positions (coins) -> USD notional for Strategy
    - Strategy signals (USD notional) -> passed through to OrderManager (which converts to coins)
    """

    def __init__(self):
        self._strategy = BacktestStrategy()
        self._settings = get_settings()

    def on_bar(
        self,
        histories: Dict[str, List[Candle]],
        account_state: AccountState,
        current_prices: Dict[str, float],
        override_positions: Optional[Dict[str, float]] = None,
    ) -> List[LiveSignal]:
        bar_data = self._candles_to_bar_data(histories)
        portfolio = self._account_to_portfolio(
            account_state, current_prices, override_positions
        )

        try:
            backtest_signals = self._strategy.on_bar(bar_data, portfolio)
        except Exception as e:
            logger.error(f"Strategy error", extra={"error": str(e)})
            return []

        return [
            LiveSignal(symbol=s.symbol, target_position=s.target_position)
            for s in backtest_signals
        ]

    def _candles_to_bar_data(self, histories: Dict[str, List[Candle]]) -> dict:
        bar_data = {}
        for symbol, candles in histories.items():
            if not candles:
                continue
            last = candles[-1]
            history_records = []
            for c in candles:
                history_records.append(
                    {
                        "timestamp": c.timestamp,
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                        "funding_rate": c.funding_rate,
                    }
                )
            hist_df = pd.DataFrame(history_records)
            bar_data[symbol] = BarData(
                symbol=symbol,
                timestamp=last.timestamp,
                open=last.open,
                high=last.high,
                low=last.low,
                close=last.close,
                volume=last.volume,
                funding_rate=last.funding_rate,
                history=hist_df,
            )
        return bar_data

    def _account_to_portfolio(
        self,
        state: AccountState,
        prices: Dict[str, float],
        override_positions: Optional[Dict[str, float]] = None,
    ) -> PortfolioState:
        positions = {}
        entry_prices = {}

        if override_positions is not None:
            for symbol, coin_qty in override_positions.items():
                price = prices.get(symbol, 0)
                if price > 0:
                    positions[symbol] = coin_qty * price
        else:
            for symbol, pos in state.positions.items():
                price = prices.get(symbol, pos.current_price)
                if price <= 0:
                    price = pos.current_price
                signed_notional = pos.size * price
                if pos.side == PositionSide.SHORT:
                    signed_notional = -signed_notional
                positions[symbol] = signed_notional
                entry_prices[symbol] = pos.entry_price

        equity = state.total_equity
        cash = state.available_balance

        if equity <= 0 and cash <= 0 and self._settings.DRY_RUN:
            equity = self._settings.DRY_RUN_INITIAL_CAPITAL
            cash = equity

        return PortfolioState(
            cash=cash,
            positions=positions,
            entry_prices=entry_prices,
            equity=equity,
        )

    def reset(self):
        self._strategy = BacktestStrategy()
