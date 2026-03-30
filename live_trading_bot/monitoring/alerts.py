import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx

from config import (
    get_settings,
    get_telegram_token,
    get_telegram_chat_id,
    get_discord_webhook,
)
from monitoring.logger import get_logger

logger = get_logger(__name__)


class Alerter:
    def __init__(self):
        self.settings = get_settings()
        self.telegram_token = get_telegram_token()
        self.telegram_chat_id = get_telegram_chat_id()
        self.discord_webhook = get_discord_webhook()

        self._client = httpx.AsyncClient(timeout=10.0)
        self._last_hourly_alert: Optional[datetime] = None
        self._hourly_message_queue: list = []

    async def close(self):
        await self._client.aclose()

    async def send_telegram(self, message: str) -> bool:
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug("Telegram not configured, skipping alert")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"

        try:
            response = await self._client.post(
                url,
                json={
                    "chat_id": self.telegram_chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
            )
            response.raise_for_status()
            logger.debug("Telegram alert sent")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram alert", extra={"error": str(e)})
            return False

    async def send_discord(self, message: str) -> bool:
        if not self.discord_webhook:
            logger.debug("Discord not configured, skipping alert")
            return False

        try:
            response = await self._client.post(
                self.discord_webhook, json={"content": message}
            )
            response.raise_for_status()
            logger.debug("Discord alert sent")
            return True
        except Exception as e:
            logger.error(f"Failed to send Discord alert", extra={"error": str(e)})
            return False

    def _tag_message(self, message: str) -> str:
        name = self.settings.ALERT_INSTANCE_NAME
        if name:
            tag = f"[{name}] "
            return tag + message
        return message

    async def send_alert(self, message: str, urgent: bool = False):
        if self.settings.DRY_RUN:
            return

        tasks = []
        message = self._tag_message(message)

        if urgent or self.settings.ALERT_ON_TRADE:
            if self.telegram_token:
                tasks.append(self.send_telegram(message))
            if self.discord_webhook:
                tasks.append(self.send_discord(message))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def alert_trade(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        pnl: Optional[float] = None,
    ):
        if not self.settings.ALERT_ON_TRADE:
            return

        notional = size * price
        pnl_str = f"\nP&L: ${pnl:.2f}" if pnl is not None else ""

        message = (
            f"🔔 <b>Trade Executed</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {side.upper()}\n"
            f"Size: {size:.6f} (${notional:.2f})\n"
            f"Price: ${price:.2f}"
            f"{pnl_str}\n\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        await self.send_alert(message, urgent=True)

    async def alert_position_closed(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        exit_price: float,
        pnl: float,
    ):
        if not self.settings.ALERT_ON_TRADE:
            return

        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

        message = (
            f"✅ <b>Position Closed</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {side.upper()}\n"
            f"Size: {size:.6f} (${size * exit_price:.2f})\n"
            f"Entry: ${entry_price:.2f}\n"
            f"Exit: ${exit_price:.2f}\n"
            f"{pnl_emoji} P&L: ${pnl:.2f}\n\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        await self.send_alert(message, urgent=True)

    async def alert_risk_event(
        self, event_type: str, details: str, action_taken: Optional[str] = None
    ):
        if not self.settings.ALERT_ON_RISK_EVENT:
            return

        action_str = f"\nAction: {action_taken}" if action_taken else ""

        message = (
            f"⚠️ <b>RISK EVENT</b>\n\n"
            f"Type: {event_type}\n"
            f"Details: {details}"
            f"{action_str}\n\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        await self.send_alert(message, urgent=True)

    async def alert_error(self, error_message: str, context: Optional[str] = None):
        if not self.settings.ALERT_ON_ERROR:
            return

        context_str = f"\nContext: {context}" if context else ""

        message = (
            f"🚨 <b>ERROR</b>\n\n"
            f"Error: {error_message}"
            f"{context_str}\n\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        await self.send_alert(message, urgent=True)

    async def send_hourly_summary(
        self, equity: float, positions: dict, daily_pnl: float, trade_count: int
    ):
        now = datetime.now(timezone.utc)

        if self._last_hourly_alert:
            hours_since = (now - self._last_hourly_alert).total_seconds() / 3600
            if hours_since < self.settings.ALERT_INTERVAL_HOURS:
                return

        self._last_hourly_alert = now

        pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"

        pos_str = ""
        if positions:
            pos_lines = []
            for symbol, pos in positions.items():
                pos_lines.append(f"  {symbol}: ${abs(pos.get('size', 0)):.2f}")
            pos_str = "\n" + "\n".join(pos_lines)

        message = (
            f"📊 <b>Hourly Summary</b>\n\n"
            f"Equity: ${equity:.2f}\n"
            f"{pnl_emoji} Daily P&L: ${daily_pnl:.2f}\n"
            f"Trades Today: {trade_count}\n"
            f"Positions:{pos_str if pos_str else ' None'}\n\n"
            f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        await self.send_alert(message, urgent=False)
