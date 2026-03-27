import asyncio
from datetime import datetime
from typing import List, Optional, Dict
import aiosqlite
import json

from .models import Trade, Position, SignalRecord, RiskEvent
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.settings = get_settings()
        self.db_path = db_path or self.settings.DB_PATH
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database not connected. Call connect() first."
        return self._db

    async def connect(self):
        async with self._lock:
            self._db = await aiosqlite.connect(self.db_path)
            await self._create_tables()
            logger.info(f"Connected to database", extra={"path": self.db_path})

    async def close(self):
        async with self._lock:
            if self._db:
                await self.db.close()
                self._db = None
                logger.info("Database connection closed")

    async def _create_tables(self):
        await self.db.executescript("""
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
            
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE NOT NULL,
                size REAL NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                side TEXT NOT NULL,
                last_updated TEXT NOT NULL
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
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
            CREATE INDEX IF NOT EXISTS idx_risk_events_timestamp ON risk_events(timestamp);
        """)
        await self.db.commit()

    async def insert_trade(self, trade: Trade) -> int:
        async with self._lock:
            cursor = await self.db.execute(
                """
                INSERT INTO trades (timestamp, symbol, side, size, price, fee, pnl, strategy_signal, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.timestamp.isoformat(),
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
            await self.db.commit()
            trade_id = cursor.lastrowid
            logger.debug(
                f"Inserted trade", extra={"trade_id": trade_id, "symbol": trade.symbol}
            )
            assert trade_id is not None
            return trade_id

    async def get_trades(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Trade]:
        query = "SELECT * FROM trades WHERE 1=1"
        params = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        async with self._lock:
            async with self.db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [
                    Trade(
                        id=row[0],
                        timestamp=datetime.fromisoformat(row[1]),
                        symbol=row[2],
                        side=row[3],
                        size=row[4],
                        price=row[5],
                        fee=row[6],
                        pnl=row[7],
                        strategy_signal=row[8],
                        order_id=row[9],
                    )
                    for row in rows
                ]

    async def upsert_position(self, position: Position):
        async with self._lock:
            await self.db.execute(
                """
                INSERT INTO positions (symbol, size, entry_price, current_price, unrealized_pnl, side, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    size = excluded.size,
                    entry_price = excluded.entry_price,
                    current_price = excluded.current_price,
                    unrealized_pnl = excluded.unrealized_pnl,
                    side = excluded.side,
                    last_updated = excluded.last_updated
                """,
                (
                    position.symbol,
                    position.size,
                    position.entry_price,
                    position.current_price,
                    position.unrealized_pnl,
                    position.side,
                    position.last_updated.isoformat(),
                ),
            )
            await self.db.commit()

    async def delete_position(self, symbol: str):
        async with self._lock:
            await self.db.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            await self.db.commit()

    async def get_all_positions(self) -> Dict[str, Position]:
        async with self._lock:
            async with self.db.execute("SELECT * FROM positions") as cursor:
                rows = await cursor.fetchall()
                return {
                    row[1]: Position(
                        id=row[0],
                        symbol=row[1],
                        size=row[2],
                        entry_price=row[3],
                        current_price=row[4],
                        unrealized_pnl=row[5],
                        side=row[6],
                        last_updated=datetime.fromisoformat(row[7]),
                    )
                    for row in rows
                }

    async def insert_signal(self, signal: SignalRecord) -> int:
        async with self._lock:
            cursor = await self.db.execute(
                """
                INSERT INTO signals (timestamp, symbol, signal_type, target_position, current_position, executed)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.timestamp.isoformat(),
                    signal.symbol,
                    signal.signal_type,
                    signal.target_position,
                    signal.current_position,
                    1 if signal.executed else 0,
                ),
            )
            await self.db.commit()
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    async def insert_risk_event(self, event: RiskEvent) -> int:
        async with self._lock:
            cursor = await self.db.execute(
                """
                INSERT INTO risk_events (timestamp, event_type, details, action_taken)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event.timestamp.isoformat(),
                    event.event_type,
                    event.details,
                    event.action_taken,
                ),
            )
            await self.db.commit()
            logger.warning(
                f"Risk event recorded",
                extra={"event_type": event.event_type, "details": event.details},
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    async def get_daily_pnl(self, symbol: Optional[str] = None) -> float:
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        query = "SELECT SUM(pnl) FROM trades WHERE timestamp >= ? AND pnl IS NOT NULL"
        params = [today_start.isoformat()]

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)

        async with self._lock:
            async with self.db.execute(query, params) as cursor:
                result = await cursor.fetchone()
                return result[0] if result and result[0] else 0.0

    async def get_trade_count_today(self) -> int:
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        async with self._lock:
            async with self.db.execute(
                "SELECT COUNT(*) FROM trades WHERE timestamp >= ?",
                (today_start.isoformat(),),
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
