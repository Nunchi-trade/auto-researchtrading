from typing import Dict, Optional
from dataclasses import dataclass

from exchange.order_manager import Signal
from exchange.types import AccountState
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PositionLimitResult:
    allowed: bool
    adjusted_size: Optional[float] = None
    reason: Optional[str] = None


class PositionLimiter:
    def __init__(self):
        self.settings = get_settings()

    def _get_equity(self, account_state: AccountState) -> float:
        return account_state.total_equity

    def check_position_limit(
        self,
        signal: Signal,
        account_state: AccountState,
        current_positions: Dict[str, float],
    ) -> PositionLimitResult:
        equity = self._get_equity(account_state)
        if equity <= 0:
            return PositionLimitResult(allowed=False, reason="Invalid equity")

        max_position_value = equity * self.settings.MAX_POSITION_PCT

        symbol = signal.symbol
        current_pos = current_positions.get(symbol, 0)
        target_pos = signal.target_position

        new_exposure = abs(target_pos)

        if new_exposure > max_position_value:
            adjusted_size = max_position_value * (1 if target_pos > 0 else -1)

            logger.info(
                f"Position size limited",
                extra={
                    "symbol": symbol,
                    "original_target": target_pos,
                    "adjusted_target": adjusted_size,
                    "max_allowed": max_position_value,
                },
            )

            return PositionLimitResult(
                allowed=True,
                adjusted_size=adjusted_size,
                reason=f"Position limited to {self.settings.MAX_POSITION_PCT:.0%} of equity",
            )

        return PositionLimitResult(allowed=True)

    def check_total_exposure(
        self,
        signal: Signal,
        account_state: AccountState,
        current_positions: Dict[str, float],
    ) -> PositionLimitResult:
        equity = self._get_equity(account_state)
        if equity <= 0:
            return PositionLimitResult(allowed=False, reason="Invalid equity")

        new_positions = dict(current_positions)
        new_positions[signal.symbol] = signal.target_position

        total_exposure = sum(abs(pos) for pos in new_positions.values())
        max_total_exposure = equity * self.settings.MAX_LEVERAGE

        if total_exposure > max_total_exposure:
            return PositionLimitResult(
                allowed=False,
                reason=f"Total exposure {total_exposure:.2f} would exceed max leverage {self.settings.MAX_LEVERAGE}x",
            )

        return PositionLimitResult(allowed=True)

    def apply_limits(
        self,
        signals: list,
        account_state: AccountState,
        current_positions: Dict[str, float],
    ) -> list:
        adjusted_signals = []

        for signal in signals:
            pos_limit = self.check_position_limit(
                signal, account_state, current_positions
            )

            if not pos_limit.allowed:
                logger.warning(
                    f"Signal rejected - position limit",
                    extra={"symbol": signal.symbol, "reason": pos_limit.reason},
                )
                continue

            if pos_limit.adjusted_size is not None:
                signal = Signal(
                    symbol=signal.symbol, target_position=pos_limit.adjusted_size
                )

            exposure_limit = self.check_total_exposure(
                signal, account_state, current_positions
            )

            if not exposure_limit.allowed:
                logger.warning(
                    f"Signal rejected - total exposure",
                    extra={"symbol": signal.symbol, "reason": exposure_limit.reason},
                )
                continue

            adjusted_signals.append(signal)

        return adjusted_signals
