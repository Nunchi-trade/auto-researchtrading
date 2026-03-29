"""Dry-run exchange — simulated order execution with real market data.

Tracks positions internally so that get_account_state() returns accurate
simulated equity and positions. Read-only market data (prices, candles,
funding rates) is fetched from the real Hyperliquid API.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from eth_account import Account
from hyperliquid.info import Info

from .types import (
    AccountState,
    Candle,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
)
from .hyperliquid import fetch_candles_paginated
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _SimPosition:
    symbol: str
    is_long: bool
    size: float  # coin qty, always positive
    entry_price: float


class DryExchange:
    """Simulated exchange for dry-run mode.

    - Orders fill instantly at current mid price
    - Positions are tracked internally with realized/unrealized PnL
    - Market data comes from the real Hyperliquid API
    """

    def __init__(self, private_key: str):
        self.settings = get_settings()
        self.account = Account.from_key(private_key)
        self.wallet_address = self.account.address
        self.query_address = (
            self.settings.HYPERLIQUID_MAIN_WALLET or self.wallet_address
        )

        self._info = Info(
            base_url=self.settings.HYPERLIQUID_API_URL, skip_ws=True
        )
        self._nonce_counter = int(time.time() * 1000)

        # Simulated state
        self._initial_equity = self.settings.DRY_RUN_INITIAL_CAPITAL
        self._realized_pnl: float = 0.0
        self._positions: Dict[str, _SimPosition] = {}

    def _get_nonce(self) -> int:
        self._nonce_counter += 1
        return self._nonce_counter

    # ── Account state ──────────────────────────────────────────────

    async def get_account_state(self) -> AccountState:
        positions: Dict[str, Position] = {}
        unrealized_pnl = 0.0
        total_margin = 0.0

        if self._positions:
            prices = await self.get_all_mid_prices()
            for symbol, sim in self._positions.items():
                current_price = prices.get(symbol, sim.entry_price)
                if sim.is_long:
                    upnl = (current_price - sim.entry_price) * sim.size
                else:
                    upnl = (sim.entry_price - current_price) * sim.size
                unrealized_pnl += upnl

                margin = sim.size * current_price / self.settings.MAX_LEVERAGE
                total_margin += margin

                positions[symbol] = Position(
                    symbol=symbol,
                    side=PositionSide.LONG if sim.is_long else PositionSide.SHORT,
                    size=sim.size,
                    entry_price=sim.entry_price,
                    current_price=current_price,
                    unrealized_pnl=upnl,
                    leverage=self.settings.MAX_LEVERAGE,
                    margin_used=margin,
                    liquidation_price=None,
                )

        total_equity = self._initial_equity + self._realized_pnl + unrealized_pnl

        return AccountState(
            wallet_address=self.query_address,
            total_equity=total_equity,
            available_balance=total_equity - total_margin,
            margin_used=total_margin,
            unrealized_pnl=unrealized_pnl,
            positions=positions,
        )

    # ── Prices ─────────────────────────────────────────────────────

    async def get_mid_price(self, symbol: str) -> float:
        mids = await asyncio.to_thread(self._info.all_mids)
        return float(mids.get(symbol, "0"))

    async def get_all_mid_prices(self) -> Dict[str, float]:
        mids = await asyncio.to_thread(self._info.all_mids)
        return {symbol: float(px) for symbol, px in mids.items()}

    # ── Leverage (no-op) ───────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        pass

    async def set_leverage_for_symbols(
        self, symbols: List[str], leverage: int
    ) -> None:
        pass

    # ── Orders ─────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> Order:
        fill_price = price or await self.get_mid_price(symbol)
        self._apply_fill(symbol, side, size, fill_price, reduce_only)

        return Order(
            id=f"dry-{self._get_nonce()}",
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=size,
            price=fill_price,
            status=OrderStatus.FILLED,
            filled_size=size,
            avg_fill_price=fill_price,
        )

    async def place_trigger_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        trigger_price: float,
        is_market: bool = True,
        tpsl: str = "sl",
    ) -> Order:
        return Order(
            id=f"dry-trigger-{self._get_nonce()}",
            symbol=symbol,
            side=side,
            order_type=OrderType.TRIGGER,
            size=size,
            price=trigger_price,
            status=OrderStatus.PENDING,
            filled_size=0.0,
            avg_fill_price=trigger_price,
        )

    def _apply_fill(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        fill_price: float,
        reduce_only: bool,
    ) -> None:
        pos = self._positions.get(symbol)
        is_buy = side == OrderSide.BUY

        if pos is None:
            if reduce_only:
                return
            self._positions[symbol] = _SimPosition(
                symbol=symbol,
                is_long=is_buy,
                size=size,
                entry_price=fill_price,
            )
            return

        is_closing = (pos.is_long and not is_buy) or (
            not pos.is_long and is_buy
        )

        if is_closing:
            close_size = min(size, pos.size)
            if pos.is_long:
                pnl = (fill_price - pos.entry_price) * close_size
            else:
                pnl = (pos.entry_price - fill_price) * close_size
            self._realized_pnl += pnl

            remaining = pos.size - close_size
            if remaining < 1e-10:
                del self._positions[symbol]
            else:
                self._positions[symbol] = _SimPosition(
                    symbol=symbol,
                    is_long=pos.is_long,
                    size=remaining,
                    entry_price=pos.entry_price,
                )

            leftover = size - close_size
            if leftover > 1e-10 and not reduce_only:
                self._positions[symbol] = _SimPosition(
                    symbol=symbol,
                    is_long=is_buy,
                    size=leftover,
                    entry_price=fill_price,
                )
        else:
            # Adding to same direction
            total_size = pos.size + size
            avg_price = (
                pos.entry_price * pos.size + fill_price * size
            ) / total_size
            self._positions[symbol] = _SimPosition(
                symbol=symbol,
                is_long=pos.is_long,
                size=total_size,
                entry_price=avg_price,
            )

    # ── Cancel (no-op) ─────────────────────────────────────────────

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        return True

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> bool:
        return True

    # ── Open orders ────────────────────────────────────────────────

    async def get_open_orders(
        self, symbol: Optional[str] = None
    ) -> List[Order]:
        return []

    # ── Market data ────────────────────────────────────────────────

    async def get_funding_rate(self, symbol: str) -> float:
        result = await asyncio.to_thread(self._info.meta_and_asset_ctxs)
        if isinstance(result, list) and len(result) > 1:
            meta = result[0]
            asset_ctxs = result[1]
            for i, coin_info in enumerate(meta.get("universe", [])):
                if coin_info.get("name") == symbol:
                    if i < len(asset_ctxs):
                        return float(asset_ctxs[i].get("funding", 0))
        return 0.0

    async def get_recent_candles(
        self,
        symbol: str,
        interval: str = "1h",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Candle]:
        candles = await fetch_candles_paginated(
            self._info, symbol, interval, start_time, end_time, limit
        )
        if candles:
            try:
                current_funding = await self.get_funding_rate(symbol)
                candles[-1] = Candle(
                    symbol=candles[-1].symbol,
                    timestamp=candles[-1].timestamp,
                    open=candles[-1].open,
                    high=candles[-1].high,
                    low=candles[-1].low,
                    close=candles[-1].close,
                    volume=candles[-1].volume,
                    funding_rate=current_funding,
                )
            except Exception as e:
                logger.warning(
                    "Failed to fetch funding rate for candle",
                    extra={"symbol": symbol, "error": str(e)},
                )
        return candles

    async def close(self) -> None:
        pass
