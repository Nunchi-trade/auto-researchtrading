import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from execution.signal_state import SignalState
from exchange.interface import Exchange
from exchange.types import Order, OrderSide, OrderStatus, OrderType, AccountState
from config.settings import Settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class ExecutionEngine:
    """Unified tick-level execution engine.

    Priority order (highest first):
    1. Emergency exit — hard adverse move beyond EMERGENCY_EXIT_PCT
    2. ATR trailing stop — from strategy's ATR_STOP_MULT
    3. Signal flip to flat — close immediately
    4. Signal reversal — close now, enter on next tick
    5. Signal entry — with slippage guard
    6. Hold — no action
    """

    def __init__(
        self,
        signal_state: SignalState,
        client: Exchange,
        settings: Settings,
        symbols: List[str],
    ):
        self.signal_state = signal_state
        self.client = client
        self.settings = settings
        self.symbols = set(symbols)

        # Position tracking (coin quantities)
        self._position_sizes: Dict[str, float] = {}  # symbol -> coin qty
        self._entry_prices: Dict[str, float] = {}  # symbol -> fill price
        self._last_executed_direction: Dict[str, int] = {}  # symbol -> +1/-1/0
        self._last_execution_attempt: Dict[str, float] = {}  # symbol -> timestamp

        # Callback for when a position is fully closed (for StopManager coordination)
        self.on_position_closed: Optional[Callable[[str], object]] = None

    async def on_tick(self, symbol: str, price: float) -> Optional[Order]:
        """Process a tick. Returns the order placed, or None."""
        if symbol not in self.symbols:
            return None
        if price <= 0:
            return None

        # Update peak/trough tracking in signal state
        self.signal_state.update_peak_trough(symbol, price)

        # Cooldown check
        now_ms = time.time() * 1000
        last_attempt = self._last_execution_attempt.get(symbol, 0)
        if now_ms - last_attempt < self.settings.EXECUTION_COOLDOWN_MS:
            return None

        current_size = self._position_sizes.get(symbol, 0.0)
        current_direction = self._last_executed_direction.get(symbol, 0)
        target_direction = self.signal_state.get_direction(symbol)
        entry_price = self._entry_prices.get(symbol, 0.0)

        # Priority 1: Emergency exit
        if current_size > 0 and entry_price > 0:
            if current_direction > 0:  # long
                adverse_pct = (entry_price - price) / entry_price
            else:  # short
                adverse_pct = (price - entry_price) / entry_price

            if adverse_pct >= self.settings.EMERGENCY_EXIT_PCT:
                logger.critical(
                    "EMERGENCY EXIT triggered",
                    extra={
                        "symbol": symbol,
                        "entry": entry_price,
                        "price": price,
                        "adverse_pct": f"{adverse_pct:.2%}",
                    },
                )
                return await self._close_position(
                    symbol, price, reason="emergency_exit"
                )

        # Priority 2: ATR trailing stop
        if current_size > 0 and entry_price > 0:
            atr = self.signal_state.signal_atr.get(symbol, 0.0)
            if atr > 0:
                # Get ATR_STOP_MULT from strategy — we use a fixed 8.0 as the strategy default
                # The strategy_15m.py has ATR_STOP_MULT = 8.0
                atr_stop_mult = 8.0  # matches strategy_15m.py constant

                if current_direction > 0:  # long
                    peak = self.signal_state.peak_prices.get(symbol, entry_price)
                    stop = peak - atr_stop_mult * atr
                    if price < stop:
                        logger.info(
                            "ATR trailing stop (long)",
                            extra={
                                "symbol": symbol,
                                "peak": peak,
                                "stop": stop,
                                "price": price,
                            },
                        )
                        return await self._close_position(
                            symbol, price, reason="atr_stop"
                        )
                elif current_direction < 0:  # short
                    trough = self.signal_state.trough_prices.get(symbol, entry_price)
                    stop = trough + atr_stop_mult * atr
                    if price > stop:
                        logger.info(
                            "ATR trailing stop (short)",
                            extra={
                                "symbol": symbol,
                                "trough": trough,
                                "stop": stop,
                                "price": price,
                            },
                        )
                        return await self._close_position(
                            symbol, price, reason="atr_stop"
                        )

        # Priority 3: Signal flip to flat
        if current_size > 0 and target_direction == 0:
            logger.info(
                "Signal flip to flat",
                extra={"symbol": symbol, "from_direction": current_direction},
            )
            return await self._close_position(symbol, price, reason="signal_flat")

        # Priority 4: Signal reversal — close first
        if (
            current_size > 0
            and target_direction != 0
            and target_direction != current_direction
        ):
            logger.info(
                "Signal reversal — closing position",
                extra={
                    "symbol": symbol,
                    "from": current_direction,
                    "to": target_direction,
                },
            )
            return await self._close_position(symbol, price, reason="signal_reversal")

        # Priority 5: Signal entry with slippage guard
        if current_size == 0 and target_direction != 0:
            signal_entry = self.signal_state.signal_entry.get(symbol, 0.0)
            if signal_entry > 0:
                slippage = abs(price - signal_entry) / signal_entry
                if slippage > self.settings.ENTRY_SLIPPAGE_PCT:
                    logger.info(
                        "Entry skipped — slippage too high",
                        extra={
                            "symbol": symbol,
                            "signal_entry": signal_entry,
                            "price": price,
                            "slippage_pct": f"{slippage:.2%}",
                            "max_slippage_pct": f"{self.settings.ENTRY_SLIPPAGE_PCT:.2%}",
                        },
                    )
                    self._last_execution_attempt[symbol] = now_ms
                    return None

            # Get target USD notional from signal state
            target_usd = self.signal_state.get_target(symbol)
            if target_usd == 0 and target_direction != 0:
                # No target stored, skip
                return None

            size_coins = abs(target_usd) / price
            if size_coins < 0.00001:
                return None

            side = OrderSide.BUY if target_direction > 0 else OrderSide.SELL

            logger.info(
                "Entry signal executing",
                extra={
                    "symbol": symbol,
                    "side": side.value,
                    "size_coins": round(size_coins, 8),
                    "price": price,
                    "target_usd": target_usd,
                },
            )

            order = await self.client.place_order(
                symbol=symbol,
                side=side,
                size=round(size_coins, 8),
                order_type=OrderType.MARKET,
                reduce_only=False,
            )

            if order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                self._position_sizes[symbol] = order.filled_size
                self._entry_prices[symbol] = order.avg_fill_price or price
                self._last_executed_direction[symbol] = target_direction

            self._last_execution_attempt[symbol] = now_ms
            return order

        # Priority 6: Hold
        return None

    async def _close_position(
        self, symbol: str, price: float, reason: str
    ) -> Optional[Order]:
        """Close the current position for a symbol."""
        current_size = self._position_sizes.get(symbol, 0.0)
        if current_size <= 0:
            return None

        current_direction = self._last_executed_direction.get(symbol, 0)
        close_side = OrderSide.SELL if current_direction > 0 else OrderSide.BUY

        logger.info(
            "Closing position",
            extra={
                "symbol": symbol,
                "reason": reason,
                "side": close_side.value,
                "size": current_size,
                "price": price,
            },
        )

        order = await self.client.place_order(
            symbol=symbol,
            side=close_side,
            size=round(current_size, 8),
            order_type=OrderType.MARKET,
            reduce_only=True,
        )

        if order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            self._position_sizes[symbol] = 0.0
            self._entry_prices[symbol] = 0.0
            self._last_executed_direction[symbol] = 0
            self.signal_state.clear_signal(symbol)

            # Notify bot to cancel exchange-side stop
            if self.on_position_closed:
                try:
                    result = self.on_position_closed(symbol)
                    if isinstance(result, Awaitable):
                        await result
                except Exception as e:
                    logger.error(
                        "on_position_closed callback error",
                        extra={"symbol": symbol, "error": str(e)},
                    )
        else:
            logger.warning(
                "Close order did not fill — clearing internal tracking (position may have been closed externally)",
                extra={
                    "symbol": symbol,
                    "status": order.status.value,
                    "reason": reason,
                },
            )
            self._position_sizes[symbol] = 0.0
            self._entry_prices[symbol] = 0.0
            self._last_executed_direction[symbol] = 0

        self._last_execution_attempt[symbol] = time.time() * 1000
        return order

    async def sync_positions(
        self, account_state: AccountState, current_prices: Dict[str, float]
    ) -> None:
        """Resync position tracking from exchange state. Called on bar close."""
        for symbol in self.symbols:
            pos = account_state.positions.get(symbol)
            if pos and pos.size > 0:
                self._position_sizes[symbol] = pos.size
                if pos.entry_price > 0:
                    self._entry_prices[symbol] = pos.entry_price
                # Determine direction from position size/sign
                # In our system, positions are stored as positive coin quantities
                # Direction comes from the signal state
                direction = self.signal_state.get_direction(symbol)
                if direction != 0:
                    self._last_executed_direction[symbol] = direction
                elif self._last_executed_direction.get(symbol) == 0:
                    # We have a position but no direction — infer from signal state target
                    target = self.signal_state.get_target(symbol)
                    self._last_executed_direction[symbol] = 1 if target > 0 else -1
            else:
                if self._position_sizes.get(symbol, 0.0) > 0:
                    logger.info(
                        "Position cleared on sync",
                        extra={"symbol": symbol},
                    )
                    self._position_sizes[symbol] = 0.0
                    self._entry_prices[symbol] = 0.0
                    self._last_executed_direction[symbol] = 0

    def reset(self) -> None:
        """Clear all internal state."""
        self._position_sizes.clear()
        self._entry_prices.clear()
        self._last_executed_direction.clear()
        self._last_execution_attempt.clear()
