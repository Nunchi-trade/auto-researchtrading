from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable
import asyncio

from exchange.types import Candle
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class BarBuilder:
    def __init__(self, symbols: List[str], interval_minutes: int = 60):
        self.settings = get_settings()
        self.symbols = symbols
        self.interval_minutes = interval_minutes

        self.price_buffers: Dict[str, deque] = {s: deque(maxlen=1000) for s in symbols}
        self.current_bars: Dict[str, dict] = {}
        self.completed_bars: Dict[str, List[Candle]] = {s: [] for s in symbols}
        self.history_buffers: Dict[str, deque] = {
            s: deque(maxlen=self.settings.LOOKBACK_BARS) for s in symbols
        }
        self._latest_funding_rates: Dict[str, float] = {s: 0.0 for s in symbols}

        self._bar_callbacks: List[Callable] = []
        self._completed_bar_ts: Dict[str, int] = {}

    def add_bar_callback(self, callback: Callable):
        self._bar_callbacks.append(callback)

    def on_tick(
        self,
        symbol: str,
        price: float,
        volume: float = 0,
        timestamp: Optional[int] = None,
        funding_rate: Optional[float] = None,
    ):
        if symbol not in self.symbols:
            return

        if funding_rate is not None:
            self._latest_funding_rates[symbol] = funding_rate

        if timestamp is None:
            timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)

        interval_start = (timestamp // (self.interval_minutes * 60 * 1000)) * (
            self.interval_minutes * 60 * 1000
        )

        self.price_buffers[symbol].append(
            {"price": price, "volume": volume, "timestamp": timestamp}
        )

        if symbol not in self.current_bars:
            self.current_bars[symbol] = {
                "timestamp": interval_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
            }
        else:
            bar = self.current_bars[symbol]
            if interval_start > bar["timestamp"]:
                self._complete_bar(symbol)
                self.current_bars[symbol] = {
                    "timestamp": interval_start,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                }
            else:
                bar["high"] = max(bar["high"], price)
                bar["low"] = min(bar["low"], price)
                bar["close"] = price
                bar["volume"] += volume

    def _complete_bar(self, symbol: str):
        if symbol not in self.current_bars:
            return

        bar = self.current_bars[symbol]
        ts = bar["timestamp"]
        if ts <= self._completed_bar_ts.get(symbol, 0):
            return
        self._completed_bar_ts[symbol] = ts
        candle = Candle(
            symbol=symbol,
            timestamp=bar["timestamp"],
            open=bar["open"],
            high=bar["high"],
            low=bar["low"],
            close=bar["close"],
            volume=bar["volume"],
            funding_rate=self._latest_funding_rates.get(symbol, 0.0),
        )

        self.completed_bars[symbol].append(candle)
        self.history_buffers[symbol].append(candle)

        logger.info(
            f"Completed bar",
            extra={
                "symbol": symbol,
                "timestamp": datetime.fromtimestamp(
                    bar["timestamp"] / 1000, tz=timezone.utc
                ).isoformat(),
                "close": bar["close"],
            },
        )

        for callback in self._bar_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(symbol, candle))
                else:
                    callback(symbol, candle)
            except Exception as e:
                logger.error(f"Bar callback error", extra={"error": str(e)})

    def add_historical_candles(self, symbol: str, candles: List[Candle]):
        new_count = 0
        for candle in candles:
            if candle.timestamp <= self._completed_bar_ts.get(symbol, 0):
                continue
            self.history_buffers[symbol].append(candle)
            new_count += 1

        if candles:
            last_candle = candles[-1]
            self.current_bars[symbol] = {
                "timestamp": last_candle.timestamp,
                "open": last_candle.open,
                "high": last_candle.high,
                "low": last_candle.low,
                "close": last_candle.close,
                "volume": last_candle.volume,
            }
            if last_candle.timestamp > self._completed_bar_ts.get(symbol, 0):
                self._completed_bar_ts[symbol] = last_candle.timestamp

        logger.info(
            f"Added historical candles",
            extra={
                "symbol": symbol,
                "count": new_count,
                "skipped": len(candles) - new_count,
                "history_size": len(self.history_buffers[symbol]),
            },
        )

    def get_history(self, symbol: str) -> List[Candle]:
        return list(self.history_buffers[symbol])

    def get_all_histories(self) -> Dict[str, List[Candle]]:
        return {s: list(self.history_buffers[s]) for s in self.symbols}

    def get_current_bar(self, symbol: str) -> Optional[dict]:
        return self.current_bars.get(symbol)

    def get_latest_price(self, symbol: str) -> Optional[float]:
        bar = self.current_bars.get(symbol)
        return bar["close"] if bar else None

    def force_complete_all_bars(self):
        for symbol in self.symbols:
            self._complete_bar(symbol)
