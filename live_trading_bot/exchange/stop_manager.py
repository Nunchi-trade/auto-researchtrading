from typing import Dict, Optional
from exchange.types import Order, OrderSide, OrderStatus, Position
from exchange.interface import Exchange
from config.settings import Settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class StopManager:
    """Manages exchange-side stop-market orders as a safety net."""

    def __init__(self, client: Exchange, settings: Settings):
        self.client = client
        self.settings = settings
        self._stops: Dict[str, Order] = {}  # symbol -> placed stop order

    async def place_stop(
        self, symbol: str, side: OrderSide, size: float, stop_price: float
    ) -> Optional[Order]:
        """Place a stop-market order. Cancels existing stop for the symbol first."""
        if self._stops.get(symbol):
            await self.cancel_stop(symbol)

        try:
            order = await self.client.place_trigger_order(
                symbol=symbol,
                side=side,
                size=size,
                trigger_price=stop_price,
            )
            if order.status in (OrderStatus.PENDING, OrderStatus.FILLED):
                self._stops[symbol] = order
                logger.info(
                    "Stop placed",
                    extra={
                        "symbol": symbol,
                        "side": side.value,
                        "stop_price": stop_price,
                        "order_id": order.id,
                    },
                )
            else:
                logger.error(
                    "Stop order rejected",
                    extra={"symbol": symbol, "status": order.status.value},
                )
            return order
        except Exception as e:
            logger.error(
                "Failed to place stop", extra={"symbol": symbol, "error": str(e)}
            )
            return None

    async def cancel_stop(self, symbol: str) -> bool:
        """Cancel stop order for a symbol. Idempotent — returns True if no stop exists."""
        stop = self._stops.pop(symbol, None)
        if not stop:
            return True

        try:
            success = await self.client.cancel_order(symbol, stop.id)
            if success:
                logger.info(
                    "Stop cancelled", extra={"symbol": symbol, "order_id": stop.id}
                )
            else:
                logger.warning(
                    "Stop cancel failed", extra={"symbol": symbol, "order_id": stop.id}
                )
            return success
        except Exception as e:
            logger.error(
                "Failed to cancel stop", extra={"symbol": symbol, "error": str(e)}
            )
            return False

    async def cancel_all_stops(self) -> bool:
        """Cancel all tracked stop orders."""
        symbols = list(self._stops.keys())
        all_ok = True
        for symbol in symbols:
            if not await self.cancel_stop(symbol):
                all_ok = False
        return all_ok

    async def refresh_stops(
        self, positions: Dict[str, Position], atrs: Dict[str, float]
    ) -> None:
        """Refresh stops for all open positions. Cancel stops for closed positions."""
        # Cancel stops for symbols with no position
        for symbol in list(self._stops.keys()):
            if symbol not in positions or positions[symbol].size == 0:
                await self.cancel_stop(symbol)

        # Place/update stops for open positions
        widening_mult = self.settings.STOP_WIDENING_MULT
        for symbol, pos in positions.items():
            if pos.size == 0:
                continue

            atr = atrs.get(symbol, 0.0)
            if atr <= 0:
                logger.warning(
                    "Skipping stop refresh — no ATR", extra={"symbol": symbol}
                )
                continue

            # stop_distance = ATR * ATR_STOP_MULT * STOP_WIDENING_MULT
            # Exchange stops must be WIDER than strategy ATR stops (strategy uses ATR_STOP_MULT from peak)
            entry = pos.entry_price if pos.entry_price > 0 else pos.current_price
            if entry <= 0:
                continue

            # For longs: stop below entry. For shorts: stop above entry.
            # Use simple fixed-distance stop from entry (not trailing)
            # since we can't track peaks/troughs on the exchange.
            # ATR_STOP_MULT = 8.0 matches strategy_15m.py constant
            atr_stop_mult = 8.0
            stop_distance = atr * atr_stop_mult * widening_mult
            if pos.side.value == "long":
                stop_price = round(entry - stop_distance, 2)
                side = OrderSide.SELL
            else:
                stop_price = round(entry + stop_distance, 2)
                side = OrderSide.BUY

            # Only refresh if stop price changed significantly (>1%)
            existing = self._stops.get(symbol)
            if existing and existing.price:
                if abs(existing.price - stop_price) / stop_price < 0.01:
                    continue

            await self.place_stop(symbol, side, pos.size, stop_price)

    def get_stop(self, symbol: str) -> Optional[Order]:
        """Get the current stop order for a symbol."""
        return self._stops.get(symbol)
