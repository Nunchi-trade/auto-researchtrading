"""SQLite repository for local testing and the side-by-side harness.

Each instance gets its own .db file — no shared state, no connection pooling needed.
"""

import aiosqlite
from datetime import datetime
from typing import Optional

from .models import Trade, SignalRecord, RiskEvent
from monitoring.logger import get_logger

logger = get_logger(__name__)


class SqliteRepository:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL NOT NULL,
                pnl REAL,
                strategy_signal TEXT,
                order_id TEXT
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                target_position REAL NOT NULL,
                current_position REAL NOT NULL,
                executed INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT NOT NULL,
                action_taken TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
            CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
        """)
        await self._db.commit()
        logger.info("Connected to SQLite", extra={"path": self._db_path})

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def insert_trade(self, trade: Trade) -> int:
        assert self._db is not None
        cursor = await self._db.execute(
            """
            INSERT INTO trades (timestamp, symbol, side, size, price, fee, pnl, strategy_signal, order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.timestamp.isoformat() if isinstance(trade.timestamp, datetime) else str(trade.timestamp),
                trade.symbol,
                trade.side,
                trade.size,
                trade.price,
                trade.fee,
                trade.pnl,
                trade.strategy_signal,
                trade.order_id,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def insert_signal(self, signal: SignalRecord) -> int:
        assert self._db is not None
        cursor = await self._db.execute(
            """
            INSERT INTO signals (timestamp, symbol, signal_type, target_position, current_position, executed)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                signal.timestamp.isoformat() if isinstance(signal.timestamp, datetime) else str(signal.timestamp),
                signal.symbol,
                signal.signal_type,
                signal.target_position,
                signal.current_position,
                signal.executed,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def insert_risk_event(self, event: RiskEvent) -> int:
        assert self._db is not None
        cursor = await self._db.execute(
            """
            INSERT INTO risk_events (timestamp, event_type, details, action_taken)
            VALUES (?, ?, ?, ?)
            """,
            (
                event.timestamp.isoformat() if isinstance(event.timestamp, datetime) else str(event.timestamp),
                event.event_type,
                event.details,
                event.action_taken,
            ),
        )
        await self._db.commit()
        logger.warning(
            "Risk event recorded",
            extra={"event_type": event.event_type, "details": event.details},
        )
        return cursor.lastrowid or 0

    async def get_daily_pnl(self, symbol: Optional[str] = None) -> float:
        assert self._db is not None
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        if symbol:
            cursor = await self._db.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE timestamp >= ? AND pnl IS NOT NULL AND symbol = ?",
                (today_start, symbol),
            )
        else:
            cursor = await self._db.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE timestamp >= ? AND pnl IS NOT NULL",
                (today_start,),
            )
        row = await cursor.fetchone()
        return float(row[0]) if row else 0.0
