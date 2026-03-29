"""Exchange protocol — structural interface for exchange implementations."""

from typing import Dict, List, Optional, Protocol, runtime_checkable

from .types import AccountState, Candle, Order, OrderSide, OrderType


@runtime_checkable
class Exchange(Protocol):
    """Protocol defining the exchange interface.

    Implementations:
    - HyperliquidClient: Live trading via Hyperliquid API
    - DryExchange: Simulated trading with real market data
    """

    wallet_address: str

    async def get_account_state(self) -> AccountState: ...

    async def get_mid_price(self, symbol: str) -> float: ...

    async def get_all_mid_prices(self) -> Dict[str, float]: ...

    async def set_leverage(self, symbol: str, leverage: int) -> None: ...

    async def set_leverage_for_symbols(
        self, symbols: List[str], leverage: int
    ) -> None: ...

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> Order: ...

    async def place_trigger_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        trigger_price: float,
        is_market: bool = True,
        tpsl: str = "sl",
    ) -> Order: ...

    async def cancel_order(self, symbol: str, order_id: str) -> bool: ...

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> bool: ...

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]: ...

    async def get_funding_rate(self, symbol: str) -> float: ...

    async def get_recent_candles(
        self,
        symbol: str,
        interval: str = "1h",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Candle]: ...

    async def close(self) -> None: ...
