from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass

from exchange.order_manager import Signal
from exchange.types import AccountState
from storage.repository import Repository
from storage.models import RiskEvent, RiskEventType
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: Optional[str] = None
    action_taken: Optional[str] = None


class RiskController:
    def __init__(self, db: Repository):
        self.settings = get_settings()
        self.db = db

        self.trading_enabled = True
        self.daily_start_equity: Optional[float] = None
        self.last_check_time: Optional[datetime] = None

        self.price_history: Dict[str, List[tuple]] = {}
        self.volatility_triggered_symbols: set = set()

    async def check_daily_loss_limit(
        self, account_state: AccountState
    ) -> RiskCheckResult:
        now = datetime.utcnow()

        if self.daily_start_equity is None or now.hour == 0 and now.minute == 0:
            self.daily_start_equity = account_state.total_equity

        daily_pnl_db = await self.db.get_daily_pnl()
        daily_pnl_pct = (
            daily_pnl_db / self.daily_start_equity if self.daily_start_equity > 0 else 0
        )

        equity_change_pct = (
            (account_state.total_equity - self.daily_start_equity)
            / self.daily_start_equity
            if self.daily_start_equity > 0
            else 0
        )

        total_daily_loss_pct = min(daily_pnl_pct, equity_change_pct)

        if total_daily_loss_pct < -self.settings.DAILY_LOSS_LIMIT_PCT:
            self.trading_enabled = False

            await self.db.insert_risk_event(
                RiskEvent(
                    id=None,
                    timestamp=now,
                    event_type=RiskEventType.DAILY_LOSS_LIMIT.value,
                    details=f"Daily loss {total_daily_loss_pct:.2%} exceeded limit {self.settings.DAILY_LOSS_LIMIT_PCT:.2%}",
                    action_taken="Trading disabled",
                )
            )

            logger.critical(
                f"Daily loss limit triggered",
                extra={
                    "daily_loss_pct": total_daily_loss_pct,
                    "limit_pct": self.settings.DAILY_LOSS_LIMIT_PCT,
                },
            )

            return RiskCheckResult(
                allowed=False,
                reason=f"Daily loss limit exceeded: {total_daily_loss_pct:.2%}",
                action_taken="Trading disabled",
            )

        return RiskCheckResult(allowed=True)

    def check_volatility_circuit_breaker(
        self, symbol: str, current_price: float, timestamp: datetime
    ) -> RiskCheckResult:
        if symbol not in self.price_history:
            self.price_history[symbol] = []

        self.price_history[symbol].append((timestamp, current_price))

        lookback_minutes = self.settings.VOLATILITY_LOOKBACK_MINUTES
        cutoff_time = timestamp - timedelta(minutes=lookback_minutes)
        self.price_history[symbol] = [
            (t, p) for t, p in self.price_history[symbol] if t > cutoff_time
        ]

        if len(self.price_history[symbol]) < 2:
            return RiskCheckResult(allowed=True)

        prices = [p for _, p in self.price_history[symbol]]
        min_price = min(prices)
        max_price = max(prices)

        if min_price > 0:
            price_change_pct = (max_price - min_price) / min_price
        else:
            price_change_pct = 0

        if price_change_pct > self.settings.VOLATILITY_CIRCUIT_BREAKER_PCT:
            self.volatility_triggered_symbols.add(symbol)

            logger.warning(
                f"Volatility circuit breaker triggered",
                extra={
                    "symbol": symbol,
                    "price_change_pct": price_change_pct,
                    "threshold_pct": self.settings.VOLATILITY_CIRCUIT_BREAKER_PCT,
                },
            )

            return RiskCheckResult(
                allowed=False,
                reason=f"Volatility circuit breaker: {symbol} moved {price_change_pct:.2%} in {lookback_minutes}min",
            )

        if symbol in self.volatility_triggered_symbols:
            if price_change_pct < self.settings.VOLATILITY_CIRCUIT_BREAKER_PCT * 0.5:
                self.volatility_triggered_symbols.discard(symbol)
                logger.info(
                    f"Volatility normalized, re-enabled trading",
                    extra={"symbol": symbol},
                )
            else:
                return RiskCheckResult(
                    allowed=False, reason=f"Volatility still elevated for {symbol}"
                )

        return RiskCheckResult(allowed=True)

    def check_no_pyramiding(
        self, signal: Signal, current_position: float
    ) -> RiskCheckResult:
        if current_position == 0:
            return RiskCheckResult(allowed=True)

        same_direction = (
            current_position > 0 and signal.target_position > current_position
        ) or (current_position < 0 and signal.target_position < current_position)

        if same_direction and abs(signal.target_position) > abs(current_position):
            return RiskCheckResult(
                allowed=False,
                reason="Pyramiding not allowed - cannot add to existing position",
            )

        return RiskCheckResult(allowed=True)

    async def check_all(
        self,
        signals: List[Signal],
        account_state: AccountState,
        current_prices: Dict[str, float],
        current_positions: Dict[str, float],
    ) -> List[Signal]:
        if not self.trading_enabled:
            logger.warning("Trading is disabled due to risk controls")
            return []

        daily_check = await self.check_daily_loss_limit(account_state)
        if not daily_check.allowed:
            return []

        allowed_signals = []
        now = datetime.utcnow()

        for signal in signals:
            symbol = signal.symbol
            current_price = current_prices.get(symbol, 0)
            current_pos = current_positions.get(symbol, 0)

            if current_price <= 0:
                logger.warning(f"Skipping signal - no price", extra={"symbol": symbol})
                continue

            vol_check = self.check_volatility_circuit_breaker(
                symbol, current_price, now
            )
            if not vol_check.allowed:
                continue

            pyramid_check = self.check_no_pyramiding(signal, current_pos)
            if not pyramid_check.allowed:
                logger.info(f"Signal blocked - pyramiding", extra={"symbol": symbol})
                continue

            allowed_signals.append(signal)

        return allowed_signals

    def enable_trading(self):
        self.trading_enabled = True
        self.daily_start_equity = None
        logger.info("Trading re-enabled")

    def disable_trading(self, reason: str = "Manual disable"):
        self.trading_enabled = False
        logger.critical(f"Trading disabled: {reason}")

    def is_trading_enabled(self) -> bool:
        return self.trading_enabled

    def reset_daily(self):
        self.daily_start_equity = None
        self.volatility_triggered_symbols.clear()
        logger.info("Daily risk limits reset")
