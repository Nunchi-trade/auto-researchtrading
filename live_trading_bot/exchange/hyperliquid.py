import json
import time
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any
import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

from .types import (
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    Position,
    PositionSide,
    AccountState,
    Ticker,
    Candle,
)
from monitoring.logger import get_logger
from config import get_settings

logger = get_logger(__name__)


class HyperliquidClient:
    def __init__(self, private_key: str, dry_run: bool = False):
        self.settings = get_settings()
        self.private_key = private_key
        self.dry_run = dry_run

        self.account = Account.from_key(private_key)
        self.wallet_address = self.account.address

        self.base_url = self.settings.HYPERLIQUID_API_URL
        self.client = httpx.AsyncClient(timeout=self.settings.REQUEST_TIMEOUT_SECONDS)

        self._nonce_counter = int(time.time() * 1000)

    async def close(self):
        await self.client.aclose()

    def _get_nonce(self) -> int:
        self._nonce_counter += 1
        return self._nonce_counter

    def _sign_l1_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        connection_id = hashlib.sha256(b"mainnet").hexdigest()

        msg = json.dumps(
            {
                "source": self.wallet_address,
                "connectionId": connection_id,
                "payload": action,
            },
            separators=(",", ":"),
        )

        signed = self.account.sign_message(encode_defunct(text=msg))

        return {"r": hex(signed.r), "s": hex(signed.s), "v": signed.v}

    async def _request(
        self, endpoint: str, data: Dict[str, Any], requires_auth: bool = False
    ) -> Any:
        url = f"{self.base_url}/{endpoint}"

        if requires_auth:
            signature = self._sign_l1_action(data)
            data["signature"] = signature

        response = await self.client.post(url, json=data)
        response.raise_for_status()
        return response.json()

    async def get_account_state(self) -> AccountState:
        data = {"type": "clearinghouseState", "user": self.wallet_address}
        result = await self._request("info", data)

        positions = {}
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
            leverage = float(pos_info.get("leverage", {}).get("value", 1))
            margin_used = float(pos_info.get("marginUsed", 0))
            liq_price = pos_info.get("liquidationPx")

            positions[coin] = Position(
                symbol=coin,
                side=side,
                size=abs(size),
                entry_price=entry_price,
                current_price=mark_price,
                unrealized_pnl=unrealized_pnl,
                leverage=leverage,
                margin_used=margin_used,
                liquidation_price=float(liq_price) if liq_price else None,
            )

        return AccountState(
            wallet_address=self.wallet_address,
            total_equity=account_value,
            available_balance=available_balance,
            margin_used=account_value - available_balance,
            unrealized_pnl=sum(p.unrealized_pnl for p in positions.values()),
            positions=positions,
        )

    async def get_mid_price(self, symbol: str) -> float:
        data = {"type": "metaAndAssetCtxs"}
        result = await self._request("info", data)

        if isinstance(result, list) and len(result) > 1:
            meta: Dict[str, Any] = result[0]
            asset_ctxs: list = result[1]

            for i, coin_info in enumerate(meta.get("universe", [])):
                if coin_info.get("name") == symbol:
                    if i < len(asset_ctxs):
                        ctx: Dict[str, Any] = asset_ctxs[i]
                        return float(ctx.get("markPx", 0))
        return 0.0

    async def get_all_mid_prices(self) -> Dict[str, float]:
        data = {"type": "metaAndAssetCtxs"}
        result = await self._request("info", data)

        prices: Dict[str, float] = {}
        if isinstance(result, list) and len(result) > 1:
            meta: Dict[str, Any] = result[0]
            asset_ctxs: list = result[1]

            for i, coin_info in enumerate(meta.get("universe", [])):
                symbol = coin_info.get("name")
                if symbol and i < len(asset_ctxs):
                    ctx: Dict[str, Any] = asset_ctxs[i]
                    prices[symbol] = float(ctx.get("markPx", 0))

        return prices

    async def _name_to_asset_index(self) -> Dict[str, int]:
        data = {"type": "metaAndAssetCtxs"}
        result = await self._request("info", data)

        name_to_idx: Dict[str, int] = {}
        if isinstance(result, list) and len(result) > 0:
            meta: Dict[str, Any] = result[0]
            for i, coin_info in enumerate(meta.get("universe", [])):
                symbol = coin_info.get("name")
                if symbol:
                    name_to_idx[symbol] = i

        return name_to_idx

    async def set_leverage(self, symbol: str, leverage: int):
        """Set leverage for a symbol. Leverage must be an integer."""
        name_to_idx = await self._name_to_asset_index()

        if symbol not in name_to_idx:
            raise ValueError(f"Symbol {symbol} not found in exchange universe")

        asset_index = name_to_idx[symbol]

        action = {
            "type": "updateLeverage",
            "asset": asset_index,
            "isCross": True,
            "leverage": leverage,
        }

        result = await self._request("exchange", {"action": action}, requires_auth=True)

        logger.info(
            f"Set leverage",
            extra={
                "symbol": symbol,
                "leverage": leverage,
                "asset_index": asset_index,
                "status": "ok",
            },
        )
        return result

    async def set_leverage_for_symbols(self, symbols: List[str], leverage: int):
        for symbol in symbols:
            try:
                await self.set_leverage(symbol, leverage)
            except Exception as e:
                logger.error(
                    f"Failed to set leverage",
                    extra={"symbol": symbol, "error": str(e)},
                )

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> Order:
        if self.dry_run:
            return Order(
                id=f"dry-run-{self._get_nonce()}",
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                status=OrderStatus.FILLED,
                filled_size=size,
                avg_fill_price=price or await self.get_mid_price(symbol),
            )

        order_data = {
            "coin": symbol,
            "isBuy": side == OrderSide.BUY,
            "sz": size,
            "limitPx": price
            if order_type == OrderType.LIMIT
            else await self.get_mid_price(symbol)
            * (1.01 if side == OrderSide.BUY else 0.99),
            "reduceOnly": reduce_only,
            "orderType": "Ioc" if order_type == OrderType.MARKET else "Limit",
        }

        action = {"type": "order", "orders": [order_data], "grouping": "na"}

        result = await self._request("exchange", {"action": action}, requires_auth=True)

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
            elif "error" in status:
                error_msg = status["error"]
                logger.error(
                    f"Order rejected",
                    extra={"symbol": symbol, "error": error_msg},
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
            else:
                return Order(
                    id=str(self._get_nonce()),
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    size=size,
                    price=price,
                    status=OrderStatus.REJECTED,
                )
        else:
            error_msg = str(statuses[0]) if statuses else "Unknown error"
            return Order(
                id=str(self._get_nonce()),
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                status=OrderStatus.REJECTED,
            )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        if self.dry_run:
            return True

        action = {"type": "cancel", "cancels": [{"coin": symbol, "oid": int(order_id)}]}

        result = await self._request("exchange", {"action": action}, requires_auth=True)
        statuses = result.get("response", {}).get("data", {}).get("statuses", [[]])

        return statuses and statuses[0] == "Success"

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> bool:
        if self.dry_run:
            return True

        open_orders = await self.get_open_orders(symbol)

        for order in open_orders:
            await self.cancel_order(order.symbol, order.id)

        return True

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        data = {"type": "openOrders", "user": self.wallet_address}
        result = await self._request("info", data)

        orders: List[Order] = []
        for raw in result:
            order_data: Dict[str, Any] = raw  # type: ignore[assignment]
            coin = order_data.get("coin")
            if not coin:
                continue
            if symbol and coin != symbol:
                continue

            side = OrderSide.BUY if order_data.get("side") == "B" else OrderSide.SELL
            order_type = (
                OrderType.LIMIT
                if order_data.get("orderType") == "limit"
                else OrderType.MARKET
            )

            orders.append(
                Order(
                    id=str(order_data.get("oid", "")),
                    symbol=coin,
                    side=side,
                    order_type=order_type,
                    size=float(order_data.get("origSz", 0)),
                    price=float(order_data.get("limitPx", 0)),
                    status=OrderStatus.PENDING,
                    filled_size=float(order_data.get("sz", 0)),
                    timestamp=datetime.fromtimestamp(
                        order_data.get("timestamp", 0) / 1000
                    ),
                )
            )

        return orders

    async def get_funding_rate(self, symbol: str) -> float:
        data = {"type": "metaAndAssetCtxs"}
        result = await self._request("info", data)

        if isinstance(result, list) and len(result) > 1:
            meta: Dict[str, Any] = result[0]
            asset_ctxs: list = result[1]

            for i, coin_info in enumerate(meta.get("universe", [])):
                if coin_info.get("name") == symbol:
                    if i < len(asset_ctxs):
                        ctx: Dict[str, Any] = asset_ctxs[i]
                        return float(ctx.get("funding", 0))
        return 0.0

    async def get_recent_candles(
        self,
        symbol: str,
        interval: str = "1h",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Candle]:
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

            data = {
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": interval,
                    "startTime": window_start,
                    "endTime": window_end,
                },
            }
            result = await self._request("info", data)

            new_candles: List[Candle] = []
            for raw in result:
                bar: Dict[str, Any] = raw  # type: ignore[assignment]
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
                f"Fetched candle batch",
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

        if candles:
            try:
                current_funding = await self.get_funding_rate(symbol)
                candles[-1].funding_rate = current_funding
            except Exception as e:
                logger.warning(
                    f"Failed to fetch funding rate for candle",
                    extra={"symbol": symbol, "error": str(e)},
                )

        return candles
