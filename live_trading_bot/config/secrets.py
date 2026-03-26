import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def get_private_key() -> str:
    key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
    if not key:
        raise ValueError("HYPERLIQUID_PRIVATE_KEY not set in environment")
    if not key.startswith("0x"):
        key = "0x" + key
    return key


def get_telegram_token() -> Optional[str]:
    return os.getenv("TELEGRAM_BOT_TOKEN")


def get_telegram_chat_id() -> Optional[str]:
    return os.getenv("TELEGRAM_CHAT_ID")


def get_discord_webhook() -> Optional[str]:
    return os.getenv("DISCORD_WEBHOOK_URL")
