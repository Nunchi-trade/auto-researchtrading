#!/usr/bin/env python3
"""
Live Trading Bot for Hyperliquid

Main entry point that orchestrates:
- Data streaming via WebSocket
- Strategy signal generation
- Order execution
- Risk management
- State persistence
- Monitoring and alerts
"""

import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from config import get_settings
from config.settings import Settings
from exchange import create_exchange, Exchange
from exchange.order_manager import OrderManager
from exchange.types import AccountState, Candle, PositionSide
from data.streamer import DataStreamer
from adapter.ensemble import EnsembleStrategy
from risk.risk_controller import RiskController
from risk.position_limiter import PositionLimiter
from storage import create_repository, Repository
from storage.models import Trade, Position, SignalRecord
from monitoring.logger import setup_logger, get_logger
from monitoring.alerts import Alerter
from monitoring.metrics import MetricsTracker
from execution.signal_state import SignalState
from execution.execution_engine import ExecutionEngine
from exchange.stop_manager import StopManager
from monitoring.watchdog import Watchdog


logger = get_logger(__name__)


class TradingBot:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

        self.client: Optional[Exchange] = None
        self.order_manager: Optional[OrderManager] = None
        self.data_streamer: Optional[DataStreamer] = None
        self.strategy: Optional[EnsembleStrategy] = None
        self.risk_controller: Optional[RiskController] = None
        self.position_limiter: Optional[PositionLimiter] = None
        self.db: Optional[Repository] = None
        self.alerter: Optional[Alerter] = None
        self.metrics: Optional[MetricsTracker] = None
        self.signal_state: Optional[SignalState] = None
        self.execution_engine: Optional[ExecutionEngine] = None
        self.stop_manager: Optional[StopManager] = None
        self.watchdog: Optional[Watchdog] = None

        self._running = False
        self._shutdown_event = asyncio.Event()

        self._current_positions: Dict[str, float] = {}
        self._current_prices: Dict[str, float] = {}
        self._last_summary_time: Optional[datetime] = None
        self._bar_count: int = 0
        self._last_heartbeat: float = 0

    async def initialize(self):
        log_dir = Path(self.settings.LOG_PATH).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        setup_logger(
            log_level="INFO", log_path=self.settings.LOG_PATH, json_format=True
        )

        logger.info(
            "Initializing trading bot",
            extra={
                "dry_run": self.settings.DRY_RUN,
                "trading_pairs": self.settings.TRADING_PAIRS,
            },
        )

        self.db = create_repository()
        await self.db.connect()

        self.client = create_exchange()

        self.order_manager = OrderManager(self.client)

        self.strategy = EnsembleStrategy()

        self.risk_controller = RiskController(self.db)

        self.position_limiter = PositionLimiter()

        self.alerter = Alerter()

        self.metrics = MetricsTracker()

        self.signal_state = SignalState()
        self.execution_engine = ExecutionEngine(
            signal_state=self.signal_state,
            client=self.client,
            settings=self.settings,
            symbols=self.settings.TRADING_PAIRS,
        )
        self.stop_manager = StopManager(self.client, self.settings)
        self.watchdog = Watchdog(self.settings, self.client, self.alerter)
        self.execution_engine.on_position_closed = self._on_execution_position_closed

        await self.client.set_leverage_for_symbols(
            self.settings.TRADING_PAIRS, int(self.settings.MAX_LEVERAGE)
        )

        if self.watchdog:
            await self.watchdog.startup_cleanup()

        self.data_streamer = DataStreamer(
            symbols=self.settings.TRADING_PAIRS,
            on_bar_callback=self._on_bar,
            on_tick_callback=self._on_tick
            if self.settings.TICK_EXECUTION_ENABLED
            else None,
        )

        account_state = await self.client.get_account_state()

        if not self.settings.DRY_RUN:
            for symbol, pos in account_state.positions.items():
                self._current_positions[symbol] = (
                    pos.size if pos.side.value == "long" else -pos.size
                )

        self.metrics.update(
            equity=account_state.total_equity,
            cash=account_state.available_balance,
            positions=self._current_positions,
        )

        if self.watchdog:
            await self.watchdog.start()

        logger.info(
            "Bot initialized",
            extra={
                "wallet": self.client.wallet_address,
                "equity": account_state.total_equity,
                "positions": list(self._current_positions.keys()),
            },
        )

        await self.alerter.send_alert(
            f"🤖 <b>Trading Bot Started</b>\n\n"
            f"Mode: {'DRY RUN' if self.settings.DRY_RUN else 'LIVE'}\n"
            f"Equity: ${account_state.total_equity:.2f}\n"
            f"Pairs: {', '.join(self.settings.TRADING_PAIRS)}",
            urgent=True,
        )

    def _positions_to_usd(self) -> Dict[str, float]:
        assert self.client is not None
        positions_usd = {}
        for symbol, coin_qty in self._current_positions.items():
            price = self._current_prices.get(symbol, 0)
            if price > 0:
                positions_usd[symbol] = coin_qty * price
            else:
                positions_usd[symbol] = coin_qty
        return positions_usd

    async def _on_bar(self, symbol: str, candle: Candle):
        """Called once per interval by DataStreamer after all symbols' bars are batched."""
        if not self._running:
            return

        self._bar_count += 1

        import time as _time
        now = _time.time()
        if now - self._last_heartbeat >= 600:
            self._last_heartbeat = now
            logger.info(
                "Heartbeat",
                extra={
                    "bars_total": self._bar_count,
                    "positions": {s: round(v, 4) for s, v in self._current_positions.items()},
                },
            )

        try:
            assert self.client is not None
            assert self.alerter is not None
            await self._process_bar(triggered_by=symbol)
        except Exception as e:
            logger.error(
                "Error processing bar", extra={"symbol": symbol, "error": str(e)}
            )
            if self.alerter is not None:
                await self.alerter.alert_error(
                    str(e), context=f"Processing bar for {symbol}"
                )

    async def _on_tick(self, symbol: str, price: float):
        if not self._running or not self.execution_engine:
            return
        try:
            self._current_prices[symbol] = price
            order = await self.execution_engine.on_tick(symbol, price)
            if order and order.status.value in ("filled", "partially_filled"):
                await self._record_execution_order(order)
                logger.info(
                    "Position after tick fill",
                    extra={
                        "symbol": symbol,
                        "side": order.side.value,
                        "filled_size": round(order.filled_size, 8),
                        "price": order.avg_fill_price,
                        "tracked_size": round(
                            self.execution_engine._position_sizes.get(symbol, 0.0), 8
                        ),
                    },
                )
        except Exception as e:
            logger.error(
                "Tick execution error", extra={"symbol": symbol, "error": str(e)}
            )

    async def _record_execution_order(self, order):
        assert self.db is not None
        assert self.metrics is not None
        assert self.alerter is not None

        pnl = None
        if self.execution_engine:
            entry = self.execution_engine._entry_prices.get(order.symbol, 0)
            if entry > 0 and order.side.value in ("sell", "buy"):
                direction = self.execution_engine._last_executed_direction.get(
                    order.symbol, 0
                )
                # This is a close order if the position was open
                if direction != 0:
                    pnl = 0  # simplified; real PnL calculation would use entry vs exit price

        await self.db.insert_trade(
            Trade(
                id=None,
                timestamp=datetime.utcnow(),
                symbol=order.symbol,
                side=order.side.value,
                size=order.filled_size,
                price=order.avg_fill_price,
                fee=order.filled_size * 0.0005,
                pnl=pnl,
                order_id=order.id,
            )
        )

        self.metrics.record_trade(
            symbol=order.symbol,
            side=order.side.value,
            size=order.filled_size,
            price=order.avg_fill_price,
            pnl=pnl,
        )

        await self.alerter.alert_trade(
            symbol=order.symbol,
            side=order.side.value,
            size=order.filled_size,
            price=order.avg_fill_price,
            pnl=pnl,
        )

    async def _on_execution_position_closed(self, symbol: str):
        if self.stop_manager:
            await self.stop_manager.cancel_stop(symbol)

    async def _process_bar(self, triggered_by: str = ""):
        assert self.client is not None
        assert self.data_streamer is not None
        assert self.strategy is not None
        assert self.risk_controller is not None
        assert self.position_limiter is not None
        assert self.order_manager is not None
        assert self.db is not None
        assert self.alerter is not None
        assert self.metrics is not None

        account_state = await self.client.get_account_state()

        prices = await self.client.get_all_mid_prices()
        for symbol in self.settings.TRADING_PAIRS:
            if symbol in prices:
                self._current_prices[symbol] = prices[symbol]

        histories = self.data_streamer.get_all_histories()

        # Sync positions from exchange (DryExchange returns simulated state)
        for symbol in self.settings.TRADING_PAIRS:
            self._current_positions.pop(symbol, None)
        for symbol, pos in account_state.positions.items():
            self._current_positions[symbol] = (
                pos.size if pos.side.value == "long" else -pos.size
            )

        positions_usd = self._positions_to_usd()

        signals = self.strategy.on_bar(
            histories=histories,
            account_state=account_state,
            current_prices=self._current_prices,
        )

        if not signals:
            logger.info("No signals generated")
            return

        logger.info(
            "Generated signals",
            extra={
                "triggered_by": triggered_by,
                "count": len(signals),
                "symbols": [s.symbol for s in signals],
            },
        )

        for signal in signals:
            await self.db.insert_signal(
                SignalRecord(
                    id=None,
                    timestamp=datetime.utcnow(),
                    symbol=signal.symbol,
                    signal_type="target_position",
                    target_position=signal.target_position,
                    current_position=positions_usd.get(signal.symbol, 0),
                    executed=False,
                )
            )

        risk_checked_signals = await self.risk_controller.check_all(
            signals=signals,
            account_state=account_state,
            current_prices=self._current_prices,
            current_positions=positions_usd,
        )

        if not risk_checked_signals:
            logger.info(
                "All signals rejected by risk controller",
                extra={
                    "original_count": len(signals),
                    "symbols": [s.symbol for s in signals],
                },
            )
            return

        limited_signals = self.position_limiter.apply_limits(
            signals=risk_checked_signals,
            account_state=account_state,
            current_positions=positions_usd,
        )

        if not limited_signals:
            logger.info(
                "All signals rejected by position limiter",
                extra={
                    "pre_limit_count": len(risk_checked_signals),
                    "symbols": [s.symbol for s in risk_checked_signals],
                },
            )
            return

        if self.settings.TICK_EXECUTION_ENABLED and self.execution_engine:
            assert self.signal_state is not None
            for signal in limited_signals:
                await self.db.insert_signal(
                    SignalRecord(
                        id=None,
                        timestamp=datetime.utcnow(),
                        symbol=signal.symbol,
                        signal_type="target_position",
                        target_position=signal.target_position,
                        current_position=positions_usd.get(signal.symbol, 0),
                        executed=False,
                    )
                )

                self.signal_state.update_signal(
                    symbol=signal.symbol,
                    target_position=signal.target_position,
                    atr=self._get_current_atr(signal.symbol),
                    entry_price=self._current_prices.get(signal.symbol, 0),
                    timestamp=datetime.utcnow(),
                )

            await self.execution_engine.sync_positions(
                account_state, self._current_prices
            )

            pos_state = {
                s: {
                    "direction": "long"
                    if self.execution_engine._last_executed_direction.get(s, 0) > 0
                    else "short"
                    if self.execution_engine._last_executed_direction.get(s, 0) < 0
                    else "flat",
                    "coins": round(
                        self.execution_engine._position_sizes.get(s, 0.0), 8
                    ),
                    "entry": round(self.execution_engine._entry_prices.get(s, 0.0), 2),
                }
                for s in self.settings.TRADING_PAIRS
                if self.execution_engine._position_sizes.get(s, 0.0) > 0
            }
            if pos_state:
                logger.info("Position state after bar", extra={"positions": pos_state})
            else:
                logger.info("No open positions after bar")

            if self.stop_manager:
                atrs = {}
                for symbol in self.settings.TRADING_PAIRS:
                    atrs[symbol] = self._get_current_atr(symbol)
                await self.stop_manager.refresh_stops(account_state.positions, atrs)
        else:
            orders = await self.order_manager.execute_signals(
                signals=limited_signals,
                positions=positions_usd,
                prices=self._current_prices,
            )

            signal_by_symbol = {s.symbol: s for s in limited_signals}

            for order in orders:
                if order.status.value in ("filled", "partially_filled"):
                    pnl = None
                    current_pos = positions_usd.get(order.symbol, 0)

                    if (current_pos > 0 and order.side.value == "sell") or (
                        current_pos < 0 and order.side.value == "buy"
                    ):
                        pnl = 0

                    await self.db.insert_trade(
                        Trade(
                            id=None,
                            timestamp=datetime.utcnow(),
                            symbol=order.symbol,
                            side=order.side.value,
                            size=order.filled_size,
                            price=order.avg_fill_price,
                            fee=order.filled_size * 0.0005,
                            pnl=pnl,
                            order_id=order.id,
                        )
                    )

                    self.metrics.record_trade(
                        symbol=order.symbol,
                        side=order.side.value,
                        size=order.filled_size,
                        price=order.avg_fill_price,
                        pnl=pnl,
                    )

                    await self.alerter.alert_trade(
                        symbol=order.symbol,
                        side=order.side.value,
                        size=order.filled_size,
                        price=order.avg_fill_price,
                        pnl=pnl,
                    )

        account_state = await self.client.get_account_state()

        # Re-sync positions after execution
        for symbol in self.settings.TRADING_PAIRS:
            self._current_positions.pop(symbol, None)
        for symbol, pos in account_state.positions.items():
            self._current_positions[symbol] = (
                pos.size if pos.side.value == "long" else -pos.size
            )

        self.metrics.update(
            equity=account_state.total_equity,
            cash=account_state.available_balance,
            positions=self._current_positions,
            unrealized_pnl=account_state.unrealized_pnl,
        )

        await self._check_hourly_summary(account_state)

    def _get_current_atr(self, symbol: str) -> float:
        if not self.strategy:
            return 0.0
        strategy = (
            self.strategy._strategy if hasattr(self.strategy, "_strategy") else None
        )
        if strategy and hasattr(strategy, "atr_at_entry"):
            return strategy.atr_at_entry.get(symbol, 0.0)
        return 0.0

    async def _check_hourly_summary(self, account_state: AccountState):
        assert self.metrics is not None
        assert self.alerter is not None
        now = datetime.utcnow()

        if self._last_summary_time:
            hours_since = (now - self._last_summary_time).total_seconds() / 3600
            if hours_since < self.settings.ALERT_INTERVAL_HOURS:
                return

        self._last_summary_time = now

        daily_pnl = self.metrics.get_daily_pnl()
        trade_count = self.metrics.get_trade_count_today()

        await self.alerter.send_hourly_summary(
            equity=account_state.total_equity,
            positions={s: {"size": p} for s, p in self._current_positions.items()},
            daily_pnl=daily_pnl,
            trade_count=trade_count,
        )

    async def run(self):
        self._running = True
        assert self.data_streamer is not None
        assert self.alerter is not None

        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, self._signal_handler)
        loop.add_signal_handler(signal.SIGTERM, self._signal_handler)

        logger.info("Starting trading bot")

        try:
            await self.data_streamer.start(client=self.client)
        except asyncio.CancelledError:
            logger.info("Bot cancelled")
        except Exception as e:
            logger.critical(f"Bot crashed", extra={"error": str(e)})
            await self.alerter.alert_error(f"Bot crashed: {str(e)}")
            raise
        finally:
            await self.shutdown()

    def _signal_handler(self):
        logger.info("Shutdown signal received")
        self._running = False
        self._shutdown_event.set()

    async def shutdown(self):
        logger.info("Shutting down trading bot")

        self._running = False

        if self.watchdog:
            await self.watchdog.stop()

        if self.stop_manager:
            await self.stop_manager.cancel_all_stops()

        if self.data_streamer:
            await self.data_streamer.stop()

        if self.client:
            await self.client.close()

        if self.db:
            await self.db.close()

        if self.alerter:
            await self.alerter.send_alert("🛑 <b>Trading Bot Stopped</b>", urgent=True)
            await self.alerter.close()

        logger.info("Shutdown complete")


async def main():
    bot = TradingBot()

    try:
        await bot.initialize()
        await bot.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
