import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

from exchange.hyperliquid import HyperliquidClient
from exchange.types import (
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    Position,
    PositionSide,
    AccountState,
)
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Signal:
    symbol: str
    target_position: float
    order_type: str = "market"


class OrderManager:
    def __init__(self, client: HyperliquidClient):
        self.client = client
        self.settings = get_settings()

        self.pending_orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []
        self._lock = asyncio.Lock()

    async def execute_signal(
        self, signal: Signal, current_position: float, current_price: float
    ) -> Optional[Order]:
        # signal.target_position and current_position are both in USD notional
        async with self._lock:
            delta = signal.target_position - current_position

            if abs(delta) < 1.0:
                logger.debug(
                    f"Signal delta too small",
                    extra={"symbol": signal.symbol, "delta_usd": delta},
                )
                return None

            if current_price <= 0:
                return None

            if delta > 0:
                side = OrderSide.BUY
            else:
                side = OrderSide.SELL

            if signal.target_position == 0:
                reduce_only = True
                size_coins = abs(current_position) / current_price
            else:
                reduce_only = False
                size_coins = abs(delta) / current_price

            size_coins = round(size_coins, 8)
            if size_coins < 0.00001:
                return None

            logger.info(
                f"Executing signal",
                extra={
                    "symbol": signal.symbol,
                    "side": side.value,
                    "size_coins": size_coins,
                    "delta_usd": delta,
                    "target_notional": signal.target_position,
                    "current_notional": current_position,
                    "reduce_only": reduce_only,
                },
            )

            try:
                order = await self.client.place_order(
                    symbol=signal.symbol,
                    side=side,
                    size=size_coins,
                    order_type=OrderType.MARKET,
                    reduce_only=reduce_only,
                )

                self.order_history.append(order)

                if order.status == OrderStatus.FILLED:
                    logger.info(
                        f"Order filled",
                        extra={
                            "order_id": order.id,
                            "symbol": order.symbol,
                            "side": order.side.value,
                            "size": order.filled_size,
                            "price": order.avg_fill_price,
                        },
                    )
                elif order.status == OrderStatus.REJECTED:
                    logger.error(
                        f"Order rejected",
                        extra={"symbol": order.symbol, "side": order.side.value},
                    )

                return order

            except Exception as e:
                logger.error(
                    f"Failed to execute order",
                    extra={
                        "symbol": signal.symbol,
                        "side": side.value,
                        "error": str(e),
                    },
                )
                return None

    async def execute_signals(
        self,
        signals: List[Signal],
        positions: Dict[str, float],
        prices: Dict[str, float],
    ) -> List[Order]:
        # positions: symbol -> USD notional (caller must convert from coins)
        orders = []

        for signal in signals:
            current_pos = positions.get(signal.symbol, 0.0)
            current_price = prices.get(signal.symbol, 0.0)

            if current_price <= 0:
                logger.warning(
                    f"Skipping signal - no price available",
                    extra={"symbol": signal.symbol},
                )
                continue

            order = await self.execute_signal(signal, current_pos, current_price)
            if order:
                orders.append(order)

        return orders

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> bool:
        try:
            result = await self.client.cancel_all_orders(symbol)
            logger.info(f"Cancelled all orders", extra={"symbol": symbol})
            return result
        except Exception as e:
            logger.error(
                f"Failed to cancel orders", extra={"symbol": symbol, "error": str(e)}
            )
            return False

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        try:
            return await self.client.get_open_orders(symbol)
        except Exception as e:
            logger.error(f"Failed to get open orders", extra={"error": str(e)})
            return []

    def get_recent_orders(self, limit: int = 100) -> List[Order]:
        return self.order_history[-limit:]
