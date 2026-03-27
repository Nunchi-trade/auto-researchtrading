from dataclasses import dataclass, field
from typing import List, Dict
import os


@dataclass
class Settings:
    TRADING_PAIRS: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    SYMBOL_WEIGHTS: Dict[str, float] = field(
        default_factory=lambda: {"BTC": 0.33, "ETH": 0.33, "SOL": 0.33}
    )
    BAR_INTERVAL: str = "15m"
    # LOOKBACK_BARS scales per interval: 1m→2000, 5m→1000, 15m→500, 1h→500
    LOOKBACK_BARS: int = 500
    # Module path for the backtest strategy; auto-derived from BAR_INTERVAL in from_env()
    STRATEGY_MODULE: str = "strategies.strategy_15m"

    BASE_POSITION_PCT: float = 0.08
    MAX_POSITION_PCT: float = 0.30
    MAX_LEVERAGE: float = 3.0

    DAILY_LOSS_LIMIT_PCT: float = 0.05
    VOLATILITY_CIRCUIT_BREAKER_PCT: float = 0.05
    VOLATILITY_LOOKBACK_MINUTES: int = 10

    COOLDOWN_BARS: int = 2
    MIN_VOTES: int = 4

    SHORT_WINDOW: int = 6
    MED_WINDOW: int = 12
    MED2_WINDOW: int = 24
    LONG_WINDOW: int = 36
    EMA_FAST: int = 7
    EMA_SLOW: int = 26
    RSI_PERIOD: int = 8
    RSI_BULL: float = 50.0
    RSI_BEAR: float = 50.0
    RSI_OVERBOUGHT: float = 69.0
    RSI_OVERSOLD: float = 31.0
    MACD_FAST: int = 14
    MACD_SLOW: int = 23
    MACD_SIGNAL: int = 9
    BB_PERIOD: int = 7
    ATR_LOOKBACK: int = 24
    ATR_STOP_MULT: float = 5.5
    TARGET_VOL: float = 0.015
    VOL_LOOKBACK: int = 36
    BASE_THRESHOLD: float = 0.012

    HYPERLIQUID_API_URL: str = "https://api.hyperliquid.xyz"
    HYPERLIQUID_WS_URL: str = "wss://api.hyperliquid.xyz/ws"

    DB_PATH: str = "trading_bot.db"
    LOG_PATH: str = "logs/bot.log"

    ALERT_INTERVAL_HOURS: float = 1.0
    ALERT_ON_TRADE: bool = True
    ALERT_ON_ERROR: bool = True
    ALERT_ON_RISK_EVENT: bool = True

    DRY_RUN: bool = False
    DRY_RUN_INITIAL_CAPITAL: float = 100_000.0

    RECONNECT_DELAY_SECONDS: float = 1.0
    MAX_RECONNECT_DELAY_SECONDS: float = 60.0
    REQUEST_TIMEOUT_SECONDS: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls()

        if val := os.getenv("TRADING_PAIRS"):
            settings.TRADING_PAIRS = val.split(",")

        if val := os.getenv("MAX_LEVERAGE"):
            settings.MAX_LEVERAGE = float(val)

        if val := os.getenv("MAX_POSITION_PCT"):
            settings.MAX_POSITION_PCT = float(val)

        if val := os.getenv("DAILY_LOSS_LIMIT_PCT"):
            settings.DAILY_LOSS_LIMIT_PCT = float(val)

        if val := os.getenv("DRY_RUN"):
            settings.DRY_RUN = val.lower() in ("true", "1", "yes")

        if val := os.getenv("DB_PATH"):
            settings.DB_PATH = val

        if val := os.getenv("BAR_INTERVAL"):
            settings.BAR_INTERVAL = val

        if val := os.getenv("STRATEGY_MODULE"):
            settings.STRATEGY_MODULE = val
        else:
            _interval_strategy_map = {
                "1m": "strategies.strategy_1m",
                "5m": "strategies.strategy_5m",
                "15m": "strategies.strategy_15m",
                "1h": "_bt_strategy",
            }
            settings.STRATEGY_MODULE = _interval_strategy_map.get(
                settings.BAR_INTERVAL, "strategies.strategy_15m"
            )

        if val := os.getenv("DRY_RUN_INITIAL_CAPITAL"):
            settings.DRY_RUN_INITIAL_CAPITAL = float(val)

        return settings


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    assert _settings is not None
    return _settings
