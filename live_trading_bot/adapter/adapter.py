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

        self._reconcile_strategy_state(bar_data, portfolio, current_prices)

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

    def _reconcile_strategy_state(
        self,
        bar_data: dict,
        portfolio: PortfolioState,
        current_prices: Dict[str, float],
    ):
        """Restore strategy tracking state for positions the exchange says are
        open but the strategy has forgotten (e.g. after a failed exit order).

        In backtesting, signals execute atomically — state mutations are always
        consistent. In live trading there's an async gap: the strategy pops
        entry_prices/peak_prices/atr_at_entry immediately on generating an exit
        signal, but the exchange may reject or partially fill the order. On the
        next bar the strategy sees the position is still open (from exchange
        state) yet has no tracking data to manage it properly.

        This reconciliation runs before every on_bar() call and is a no-op in
        the normal case (strategy state already in sync with exchange).
        """
        strategy = self._strategy

        for symbol, pos_notional in portfolio.positions.items():
            if abs(pos_notional) < 1.0:
                continue
            # Exchange says position exists, but strategy has no memory of it
            if symbol not in strategy.entry_prices:
                price = current_prices.get(symbol, 0)
                if price <= 0:
                    continue

                entry = portfolio.entry_prices.get(symbol, price)
                strategy.entry_prices[symbol] = entry
                # Conservative peak: max of entry and current price
                strategy.peak_prices[symbol] = max(entry, price)

                # Calculate ATR from available history
                if symbol in bar_data:
                    hist = bar_data[symbol].history
                    if len(hist) > 25:
                        highs = hist["high"].values[-24:]
                        lows = hist["low"].values[-24:]
                        closes = hist["close"].values[-25:-1]
                        tr = np.maximum(
                            highs - lows,
                            np.maximum(np.abs(highs - closes), np.abs(lows - closes)),
                        )
                        strategy.atr_at_entry[symbol] = float(np.mean(tr))
                    else:
                        strategy.atr_at_entry[symbol] = price * 0.02
                else:
                    strategy.atr_at_entry[symbol] = price * 0.02

                # Mark as already-pyramided to avoid re-pyramiding a restored
                # position, and cancel any cooldown from the failed exit
                strategy.pyramided[symbol] = True
                strategy.exit_bar.pop(symbol, None)

                logger.info(
                    "Reconciled strategy state for orphaned position",
                    extra={"symbol": symbol, "entry": entry, "price": price},
                )

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
