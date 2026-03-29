import asyncio
import os
import time
from typing import Optional

from config.settings import Settings
from exchange.interface import Exchange
from monitoring.logger import get_logger

logger = get_logger(__name__)


class Watchdog:
    """Heartbeat file writer and startup cleanup for crash recovery."""

    def __init__(self, settings: Settings, client: Exchange, alerter=None):
        self.settings = settings
        self.client = client
        self.alerter = alerter
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the heartbeat loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Watchdog started",
            extra={
                "interval_seconds": self.settings.WATCHDOG_INTERVAL_SECONDS,
                "heartbeat_path": self.settings.WATCHDOG_HEARTBEAT_PATH,
            },
        )

    async def stop(self) -> None:
        """Stop the heartbeat loop and remove heartbeat file."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Remove heartbeat file
        try:
            if os.path.exists(self.settings.WATCHDOG_HEARTBEAT_PATH):
                os.remove(self.settings.WATCHDOG_HEARTBEAT_PATH)
        except OSError:
            pass

        logger.info("Watchdog stopped")

    async def _loop(self) -> None:
        """Write heartbeat timestamp to file at regular intervals."""
        while self._running:
            try:
                ts_ms = int(time.time() * 1000)
                with open(self.settings.WATCHDOG_HEARTBEAT_PATH, "w") as f:
                    f.write(str(ts_ms))
            except OSError as e:
                logger.warning("Failed to write heartbeat", extra={"error": str(e)})

            await asyncio.sleep(self.settings.WATCHDOG_INTERVAL_SECONDS)

    def is_alive(self) -> bool:
        """Check if the heartbeat file is recent enough."""
        try:
            if not os.path.exists(self.settings.WATCHDOG_HEARTBEAT_PATH):
                return False
            mtime = os.path.getmtime(self.settings.WATCHDOG_HEARTBEAT_PATH)
            age = time.time() - mtime
            return age < self.settings.WATCHDOG_INTERVAL_SECONDS * 3
        except OSError:
            return False

    async def startup_cleanup(self) -> None:
        """Cancel stale orders from previous crash, but preserve exchange-side stops."""
        logger.info(
            "Running startup cleanup — cancelling stale orders (preserving stops)"
        )
        try:
            open_orders = await self.client.get_open_orders()
            cancelled = 0
            preserved = 0
            for order in open_orders:
                if order.order_type and order.order_type.value == "trigger":
                    preserved += 1
                    continue
                await self.client.cancel_order(order.symbol, order.id)
                cancelled += 1
            logger.info(
                "Startup cleanup complete",
                extra={"cancelled": cancelled, "preserved_stops": preserved},
            )

            if self.alerter:
                await self.alerter.alert_risk_event(
                    event_type="startup_cleanup",
                    details=f"Cancelled {cancelled} stale orders, preserved {preserved} stop orders",
                    action_taken="cancel_non_stop_orders",
                )
        except Exception as e:
            logger.error("Startup cleanup failed", extra={"error": str(e)})
            if self.alerter:
                await self.alerter.alert_error(
                    error_message="Startup cleanup failed",
                    context=str(e),
                )
