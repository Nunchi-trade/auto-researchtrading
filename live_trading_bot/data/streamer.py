import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable
import websockets

from exchange.types import Candle
from exchange.interface import Exchange
from data.bar_builder import BarBuilder
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


def parse_interval_minutes(interval: str) -> int:
    raw = interval.rstrip("mhs")
    value = int(raw)
    unit = interval[-1]
    if unit == "h":
        return value * 60
    if unit == "m":
        return value
    if unit == "s":
        return max(1, value // 60)
    return value


class DataStreamer:
    def __init__(
        self,
        symbols: List[str],
        on_bar_callback: Optional[Callable] = None,
        on_tick_callback: Optional[Callable] = None,
    ):
        self.settings = get_settings()
        self.symbols = symbols
        self.on_bar_callback = on_bar_callback
        self.on_tick_callback = on_tick_callback

        self.ws_url = self.settings.HYPERLIQUID_WS_URL
        interval_minutes = parse_interval_minutes(self.settings.BAR_INTERVAL)
        self.bar_builder = BarBuilder(symbols, interval_minutes=interval_minutes)

        self._ws: Optional[websockets.ClientConnection] = None
        self._running = False
        self._reconnect_delay = self.settings.RECONNECT_DELAY_SECONDS
        self._subscription_ids: Dict[str, str] = {}

        self.latest_prices: Dict[str, float] = {}
        self.latest_volumes: Dict[str, float] = {}
        self._last_candle_ts: Dict[str, int] = {}
        self._client: Optional[Exchange] = None
        self._bar_count_since_funding_fetch: int = 0
        self._FUNDING_FETCH_INTERVAL: int = 8

        # Bar batching: collect per-symbol completions, fire callback once per interval
        self._pending_bar_symbols: set = set()
        self._batch_interval_ts: Optional[int] = None

    async def start(self, client: Optional[Exchange] = None):
        self._running = True
        self._client = client

        if client:
            await self._load_historical_data(client)

        self.bar_builder.add_bar_callback(self._on_symbol_bar_complete)
        self.bar_builder.add_bar_callback(self._on_bar_for_funding)

        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                logger.error(f"WebSocket error", extra={"error": str(e)})
                if self._running:
                    logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2,
                        self.settings.MAX_RECONNECT_DELAY_SECONDS,
                    )

    async def _load_historical_data(self, client: Exchange):
        logger.info("Loading historical data...")

        for symbol in self.symbols:
            try:
                candles = await client.get_recent_candles(
                    symbol=symbol,
                    interval=self.settings.BAR_INTERVAL,
                    limit=self.settings.LOOKBACK_BARS,
                )
                self.bar_builder.add_historical_candles(symbol, candles)

                if candles:
                    self.latest_prices[symbol] = candles[-1].close

                logger.info(
                    f"Loaded historical data",
                    extra={"symbol": symbol, "bars": len(candles)},
                )
            except Exception as e:
                logger.error(
                    f"Failed to load historical data",
                    extra={"symbol": symbol, "error": str(e)},
                )

    async def _connect_and_listen(self):
        logger.info(f"Connecting to WebSocket", extra={"url": self.ws_url})

        async with websockets.connect(
            self.ws_url,
            ping_interval=20,
            ping_timeout=60,
            close_timeout=10,
        ) as ws:
            self._ws = ws
            self._reconnect_delay = self.settings.RECONNECT_DELAY_SECONDS

            await self._subscribe()
            logger.info("WebSocket connected and subscribed")

            async for message in ws:
                if not self._running:
                    break

                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error", extra={"error": str(e)})
                except Exception as e:
                    logger.error(f"Message handling error", extra={"error": str(e)})

    async def _subscribe(self):
        assert self._ws is not None
        for symbol in self.symbols:
            subscription = {"method": "subscribe", "subscription": {"type": "allMids"}}
            await self._ws.send(json.dumps(subscription))

            subscription = {
                "method": "subscribe",
                "subscription": {"type": "l2Book", "coin": symbol},
            }
            await self._ws.send(json.dumps(subscription))

            subscription = {
                "method": "subscribe",
                "subscription": {
                    "type": "candle",
                    "coin": symbol,
                    "interval": self.settings.BAR_INTERVAL,
                },
            }
            await self._ws.send(json.dumps(subscription))

            logger.debug(f"Subscribed to {symbol}")

    async def _handle_message(self, data: dict):
        channel = data.get("channel")

        if channel == "allMids":
            mids = data.get("data", {}).get("mids", {})
            for symbol, price_str in mids.items():
                if symbol in self.symbols:
                    price = float(price_str)
                    self.latest_prices[symbol] = price
                    self.bar_builder.on_tick(symbol, price)

                    if self.on_tick_callback:
                        await self._safe_callback(self.on_tick_callback, symbol, price)

        elif channel == "l2Book":
            book_data = data.get("data", {})
            symbol = book_data.get("coin")
            if symbol in self.symbols:
                levels = book_data.get("levels", [[], []])
                if levels and levels[0]:
                    best_bid = float(levels[0][0].get("px", 0))
                    best_ask = (
                        float(levels[1][0].get("px", 0))
                        if len(levels) > 1 and levels[1]
                        else best_bid
                    )
                    mid = (best_bid + best_ask) / 2

                    self.latest_prices[symbol] = mid
                    self.bar_builder.on_tick(symbol, mid)

        elif channel == "subscriptionResponse":
            logger.debug(f"Subscription response: {data}")

        elif channel == "candle":
            candle_data = data.get("data", {})
            coin = candle_data.get("coin") or candle_data.get("s")
            if coin in self.symbols:
                candle_ts = int(candle_data.get("t", 0))

                last_ts = self._last_candle_ts.get(coin, 0)
                if candle_ts <= last_ts:
                    return
                self._last_candle_ts[coin] = candle_ts

                candle = Candle(
                    symbol=coin,
                    timestamp=candle_ts,
                    open=float(candle_data.get("o", 0)),
                    high=float(candle_data.get("h", 0)),
                    low=float(candle_data.get("l", 0)),
                    close=float(candle_data.get("c", 0)),
                    volume=float(candle_data.get("v", 0)),
                    funding_rate=self.bar_builder._latest_funding_rates.get(coin, 0.0),
                )

                self.bar_builder.current_bars[coin] = {
                    "timestamp": candle.timestamp,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
                self.latest_volumes[coin] = candle.volume

                self.bar_builder._complete_bar(coin)

    async def _fetch_funding_rates(self):
        if not self._client:
            return
        for symbol in self.symbols:
            try:
                rate = await self._client.get_funding_rate(symbol)
                self.bar_builder.on_tick(
                    symbol, self.latest_prices.get(symbol, 0.0), funding_rate=rate
                )
            except Exception as e:
                logger.warning(
                    f"Failed to fetch funding rate",
                    extra={"symbol": symbol, "error": str(e)},
                )

    async def _on_symbol_bar_complete(self, symbol: str, candle: Candle):
        """Collect per-symbol bar completions into a batch.

        Only fires the callback when ALL symbols have reported for the interval.
        No early/partial flush — that was causing duplicate order execution when
        late-arriving symbols (SOL) split the batch into two callbacks.
        """
        self._batch_interval_ts = candle.timestamp
        self._pending_bar_symbols.add(symbol)

        if self._pending_bar_symbols >= set(self.symbols):
            await self._flush_bar_batch()

    async def _flush_bar_batch(self):
        """Fire the bot callback once for the collected batch."""
        symbols = list(self._pending_bar_symbols)
        self._pending_bar_symbols.clear()
        self._batch_interval_ts = None

        if not symbols:
            return

        if self.on_bar_callback:
            await self._safe_callback(self.on_bar_callback, symbols[0],
                self.bar_builder.get_history(symbols[0])[-1] if self.bar_builder.get_history(symbols[0]) else None)

    async def _on_bar_for_funding(self, symbol: str, candle: Candle):
        self._bar_count_since_funding_fetch += 1
        if self._bar_count_since_funding_fetch >= self._FUNDING_FETCH_INTERVAL:
            self._bar_count_since_funding_fetch = 0
            await self._fetch_funding_rates()

    async def _safe_callback(self, callback: Callable, *args):
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"Callback error", extra={"error": str(e)})

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()
        logger.info("Data streamer stopped")

    def get_latest_prices(self) -> Dict[str, float]:
        return self.latest_prices.copy()

    def get_history(self, symbol: str) -> List[Candle]:
        return self.bar_builder.get_history(symbol)

    def get_all_histories(self) -> Dict[str, List[Candle]]:
        return self.bar_builder.get_all_histories()
