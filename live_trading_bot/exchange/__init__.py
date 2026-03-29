from .interface import Exchange
from .hyperliquid import HyperliquidClient
from .order_manager import OrderManager, Signal
from .stop_manager import StopManager
from .types import *


def create_exchange() -> Exchange:
    """Factory: returns DryExchange or HyperliquidClient based on settings."""
    from config import get_settings, get_private_key

    settings = get_settings()
    private_key = get_private_key()
    if settings.DRY_RUN:
        from .dry_exchange import DryExchange

        return DryExchange(private_key)
    return HyperliquidClient(private_key)
