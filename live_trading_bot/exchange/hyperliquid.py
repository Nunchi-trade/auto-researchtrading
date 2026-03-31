"""Hyperliquid exchange client wrapping the official hyperliquid-python-sdk.

Provides an async interface that returns the bot's internal types (Order,
AccountState, etc.) while delegating signing, wire formats, and API calls
to the SDK.

This is the **live** implementation — it places real orders on Hyperliquid.
For simulated trading, see dry_exchange.py.
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))


from .types import (
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    Position,
    PositionSide,
    AccountState,
    Candle,
)
from ..monitoring.logger import get_logger
from ..config import get_settings

logger = get_logger(__name__)


# ── Shared helpers ──────────────────────────────────────────────────


async def fetch_candles_paginated(
    info: Info,
    symbol: str,
    interval: str,
    start_time: Optional[int],
    end_time: Optional[int],
    limit: int,
) -> List[Candle]:
    """Fetch candles with pagination and deduplication.

    Shared by HyperliquidClient and DryExchange (both delegate to Info API).
    Does NOT attach a funding rate to the last candle — callers handle that.
    """
    if end_time is None:
        end_time = int(time.time() * 1000)

    raw = interval.rstrip("mhs")
    value = int(raw)
    unit = interval[-1]
    if unit == "h":
        interval_minutes = value * 60
    elif unit == "m":
        interval_minutes = value
    elif unit == "s":
        interval_minutes = max(1, value // 60)
    else:
        interval_minutes = 60

    if start_time is None:
        start_time = end_time - (limit * interval_minutes * 60 * 1000)

    all_candles: List[Candle] = []
    window_end = end_time
    ms_per_window = limit * interval_minutes * 60 * 1000

    while len(all_candles) < limit and window_end > start_time:
        window_start = max(start_time, window_end - ms_per_window)

        result = await asyncio.to_thread(
            info.candles_snapshot, symbol, interval, window_start, window_end
        )

        new_candles: List[Candle] = []
        for bar in result:
            new_candles.append(
                Candle(
                    symbol=symbol,
                    timestamp=int(bar.get("t", 0)),
                    open=float(bar.get("o", 0)),
                    high=float(bar.get("h", 0)),
                    low=float(bar.get("l", 0)),
                    close=float(bar.get("c", 0)),
                    volume=float(bar.get("v", 0)),
                    funding_rate=0.0,
                )
            )

        if not new_candles:
            break

        window_end = new_candles[0].timestamp - 1
        all_candles.extend(new_candles)

        logger.info(
            "Fetched candle batch",
            extra={
                "symbol": symbol,
                "batch_size": len(new_candles),
                "total": len(all_candles),
            },
        )

    seen_ts: set[int] = set()
    unique: List[Candle] = []
    for c in all_candles:
        if c.timestamp not in seen_ts:
            seen_ts.add(c.timestamp)
            unique.append(c)

    candles = sorted(unique, key=lambda x: x.timestamp)

    if len(candles) > limit:
        candles = candles[-limit:]

    return candles


# ── Live client ─────────────────────────────────────────────────────


class HyperliquidClient:
    def __init__(self, private_key: str):
        self.settings = get_settings()

        self.account = Account.from_key(private_key)
        self.wallet_address = self.account.address
        # API wallets don't hold equity — query the main wallet for account state.
        # If HYPERLIQUID_MAIN_WALLET is unset, the PK is the main wallet's.
        self.query_address = (
            self.settings.HYPERLIQUID_MAIN_WALLET or self.wallet_address
        )

        base_url = self.settings.HYPERLIQUID_API_URL

        self._info = Info(base_url=base_url, skip_ws=True)
        self._exchange = Exchange(
            wallet=self.account,
            base_url=base_url,
            account_address=self.query_address,
        )

        self._nonce_counter = int(time.time() * 1000)

        # Cache szDecimals for each asset (fetched lazily)
        self._sz_decimals: Dict[str, int] = {}

    def _round_size(self, symbol: str, size: float) -> float:
        """Round order size to the asset's szDecimals precision."""
        if symbol not in self._sz_decimals:
            meta = self._info.meta()
            for asset in meta.get("universe", []):
                self._sz_decimals[asset["name"]] = asset.get("szDecimals", 0)
        decimals = self._sz_decimals.get(symbol, 0)
        return round(size, decimals)

    async def close(self):
        pass

    def _get_nonce(self) -> int:
        self._nonce_counter += 1
        return self._nonce_counter

    # ── Account state ──────────────────────────────────────────────

    async def get_account_state(self) -> AccountState:
        result = await asyncio.to_thread(self._info.user_state, self.query_address)

        positions: Dict[str, Position] = {}
        margin_summary = result.get("marginSummary", {})
        account_value = float(margin_summary.get("accountValue", 0))
        available_balance = float(margin_summary.get("availableBalance", 0))

        for pos_data in result.get("assetPositions", []):
            pos_info = pos_data.get("position", {})
            coin = pos_info.get("coin")
            if not coin:
                continue

            size = float(pos_info.get("szi", 0))
            if size == 0:
                continue

            side = PositionSide.LONG if size > 0 else PositionSide.SHORT
            entry_price = float(pos_info.get("entryPx", 0))
            mark_price = float(pos_info.get("markPx", 0))
            unrealized_pnl = float(pos_info.get("unrealizedPnl", 0))
            leverage_raw = pos_info.get("leverage", {})
            leverage_val = (
                float(leverage_raw.get("value", 1))
                if isinstance(leverage_raw, dict)
                else float(leverage_raw)
            )
            margin_used = float(pos_info.get("marginUsed", 0))
            liq_price = pos_info.get("liquidationPx")

            positions[coin] = Position(
                symbol=coin,
                side=side,
                size=abs(size),
                entry_price=entry_price,
                current_price=mark_price,
                unrealized_pnl=unrealized_pnl,
                leverage=leverage_val,
                margin_used=margin_used,
                liquidation_price=float(liq_price) if liq_price else None,
            )

        return AccountState(
            wallet_address=self.query_address,
            total_equity=account_value,
            available_balance=available_balance,
            margin_used=account_value - available_balance,
            unrealized_pnl=sum(p.unrealized_pnl for p in positions.values()),
            positions=positions,
        )

    # ── Prices ─────────────────────────────────────────────────────

    async def get_mid_price(self, symbol: str) -> float:
        mids = await asyncio.to_thread(self._info.all_mids)
        price_str = mids.get(symbol, "0")
        return float(price_str)

    async def get_all_mid_prices(self) -> Dict[str, float]:
        mids = await asyncio.to_thread(self._info.all_mids)
        return {symbol: float(px) for symbol, px in mids.items()}

    # ── Leverage ───────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int):
        result = await asyncio.to_thread(
            self._exchange.update_leverage, leverage, symbol, True
        )
        logger.info(
            "Set leverage",
            extra={"symbol": symbol, "leverage": leverage, "status": "ok"},
        )
        return result

    async def set_leverage_for_symbols(self, symbols: List[str], leverage: int):
        for symbol in symbols:
            try:
                await self.set_leverage(symbol, leverage)
            except Exception as e:
                logger.error(
                    "Failed to set leverage",
                    extra={"symbol": symbol, "error": str(e)},
                )

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
        size = self._round_size(symbol, size)
        is_buy = side == OrderSide.BUY
        slippage = 0.05  # 5% slippage for market orders

        if order_type == OrderType.MARKET:
            limit_px = self._exchange._slippage_price(symbol, is_buy, slippage, price)
            sdk_order_type: Any = {"limit": {"tif": "Ioc"}}
        else:
            limit_px = price or await self.get_mid_price(symbol)
            sdk_order_type = {"limit": {"tif": "Gtc"}}

        result = await asyncio.to_thread(
            self._exchange.order,
            symbol,
            is_buy,
            size,
            limit_px,
            sdk_order_type,
            reduce_only,
        )

        return self._parse_order_result(result, symbol, side, order_type, size, price)

    async def place_trigger_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        trigger_price: float,
        is_market: bool = True,
        tpsl: str = "sl",
    ) -> Order:
        size = self._round_size(symbol, size)

        sdk_order_type: Any = {
            "trigger": {
                "triggerPx": trigger_price,
                "isMarket": is_market,
                "tpsl": tpsl,
            }
        }

        result = await asyncio.to_thread(
            self._exchange.order,
            symbol,
            side == OrderSide.BUY,
            size,
            trigger_price,
            sdk_order_type,
            True,  # reduce_only
        )

        return self._parse_trigger_result(result, symbol, side, size, trigger_price)

    def _parse_order_result(
        self,
        result: Any,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        size: float,
        price: Optional[float],
    ) -> Order:
        if result is None or result.get("status") == "err":
            error_msg = (
                result.get("response", "Unknown error") if result else "No response"
            )
            logger.error("Order rejected", extra={"symbol": symbol, "error": error_msg})
            return Order(
                id=str(self._get_nonce()),
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                status=OrderStatus.REJECTED,
            )

        response_data = result.get("response", {}).get("data", {})
        statuses = response_data.get("statuses", [])

        if statuses and isinstance(statuses[0], dict):
            status = statuses[0]

            if "filled" in status:
                filled_data = status["filled"]
                filled_size = float(filled_data.get("totalSz", 0))
                avg_fill_price = float(filled_data.get("avgPx", 0))
                order_id = filled_data.get("oid", self._get_nonce())

                fill_status = (
                    OrderStatus.PARTIALLY_FILLED
                    if filled_size < size
                    else OrderStatus.FILLED
                )

                return Order(
                    id=str(order_id),
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    size=size,
                    price=price,
                    status=fill_status,
                    filled_size=filled_size,
                    avg_fill_price=avg_fill_price,
                )
            elif "resting" in status:
                oid = status["resting"].get("oid", self._get_nonce())
                return Order(
                    id=str(oid),
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    size=size,
                    price=price,
                    status=OrderStatus.PENDING,
                )
            elif "error" in status:
                logger.error(
                    "Order rejected",
                    extra={"symbol": symbol, "error": status["error"]},
                )

        return Order(
            id=str(self._get_nonce()),
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=size,
            price=price,
            status=OrderStatus.REJECTED,
        )

    def _parse_trigger_result(
        self,
        result: Any,
        symbol: str,
        side: OrderSide,
        size: float,
        trigger_price: float,
    ) -> Order:
        if result is None or result.get("status") == "err":
            error_msg = (
                result.get("response", "Unknown error") if result else "No response"
            )
            logger.error(
                "Trigger order rejected",
                extra={"symbol": symbol, "error": error_msg},
            )
            return Order(
                id=str(self._get_nonce()),
                symbol=symbol,
                side=side,
                order_type=OrderType.TRIGGER,
                size=size,
                price=trigger_price,
                status=OrderStatus.REJECTED,
            )

        response_data = result.get("response", {}).get("data", {})
        statuses = response_data.get("statuses", [])

        if statuses and isinstance(statuses[0], dict):
            status = statuses[0]
            if "resting" in status:
                oid = status["resting"].get("oid", self._get_nonce())
                return Order(
                    id=str(oid),
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.TRIGGER,
                    size=size,
                    price=trigger_price,
                    status=OrderStatus.PENDING,
                    filled_size=0.0,
                    avg_fill_price=trigger_price,
                )

        return Order(
            id=str(self._get_nonce()),
            symbol=symbol,
            side=side,
            order_type=OrderType.TRIGGER,
            size=size,
            price=trigger_price,
            status=OrderStatus.REJECTED,
        )

    # ── Cancel ─────────────────────────────────────────────────────

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            result = await asyncio.to_thread(
                self._exchange.cancel, symbol, int(order_id)
            )
            return result.get("status") == "ok"
        except Exception as e:
            logger.error(
                "Failed to cancel order",
                extra={"symbol": symbol, "order_id": order_id, "error": str(e)},
            )
            return False

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> bool:
        open_orders = await self.get_open_orders(symbol)
        for order in open_orders:
            await self.cancel_order(order.symbol, order.id)
        return True

    # ── Open orders ────────────────────────────────────────────────

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        result = await asyncio.to_thread(
            self._info.frontend_open_orders, self.query_address
        )

        orders: List[Order] = []
        for order_data in result:
            coin = order_data.get("coin")
            if not coin:
                continue
            if symbol and coin != symbol:
                continue

            ot_side = OrderSide.BUY if order_data.get("side") == "B" else OrderSide.SELL
            is_trigger = order_data.get("isTrigger", False)
            raw_ot = order_data.get("orderType", "")
            if is_trigger or (isinstance(raw_ot, dict) and "trigger" in raw_ot):
                ot_type = OrderType.TRIGGER
                price = float(
                    order_data.get("triggerPx", 0) or order_data.get("limitPx", 0)
                )
            elif raw_ot == "Limit" or raw_ot == "limit":
                ot_type = OrderType.LIMIT
                price = float(order_data.get("limitPx", 0))
            else:
                ot_type = OrderType.MARKET
                price = float(order_data.get("limitPx", 0))

            orders.append(
                Order(
                    id=str(order_data.get("oid", "")),
                    symbol=coin,
                    side=ot_side,
                    order_type=ot_type,
                    size=float(order_data.get("origSz", 0)),
                    price=price,
                    status=OrderStatus.PENDING,
                    filled_size=float(order_data.get("sz", 0)),
                    timestamp=datetime.fromtimestamp(
                        order_data.get("timestamp", 0) / 1000
                    ),
                )
            )
        return orders

    # ── Fills & funding history ─────────────────────────────────────

    async def get_user_fills(self, start_time: int, end_time: int) -> list[dict]:
        """Get fills with closedPnl for a time window. Times in ms."""
        return await asyncio.to_thread(
            self._info.user_fills_by_time, self.query_address, start_time, end_time
        )

    async def get_funding_history(
        self, start_time: int, end_time: int | None = None
    ) -> list[dict]:
        """Get funding payments for a time window. start_time in ms."""
        return await asyncio.to_thread(
            self._info.user_funding_history, self.query_address, start_time, end_time
        )

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
