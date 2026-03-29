import asyncpg
from datetime import datetime
from typing import List, Optional, Dict

from .models import Trade, Position, SignalRecord, RiskEvent, ParamSnapshot
from config import get_settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class Database:
    def __init__(self):
        self.settings = get_settings()
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def pool(self) -> asyncpg.Pool:
        assert self._pool is not None, "Database not connected. Call connect() first."
        return self._pool

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            dsn=self.settings.SUPABASE_DB_URL,
            min_size=1,
            max_size=5,
        )
        logger.info("Connected to Supabase PostgreSQL")

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Database connection pool closed")

    # --- Trades ---

    async def insert_trade(self, trade: Trade) -> int:
        row = await self.pool.fetchrow(
            """
            INSERT INTO trades (timestamp, symbol, side, size, price, fee, pnl, strategy_signal, order_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            trade.timestamp,
            trade.symbol,
            trade.side,
            trade.size,
            trade.price,
            trade.fee,
            trade.pnl,
            trade.strategy_signal,
            trade.order_id,
        )
        trade_id = row["id"]
        logger.debug(
            "Inserted trade", extra={"trade_id": trade_id, "symbol": trade.symbol}
        )
        return trade_id

    async def get_trades(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Trade]:
        conditions = []
        params = []
        idx = 1

        if symbol:
            conditions.append(f"symbol = ${idx}")
            params.append(symbol)
            idx += 1
        if start_time:
            conditions.append(f"timestamp >= ${idx}")
            params.append(start_time)
            idx += 1
        if end_time:
            conditions.append(f"timestamp <= ${idx}")
            params.append(end_time)
            idx += 1

        where = " AND ".join(conditions) if conditions else "TRUE"
        params.append(limit)

        query = (
            f"SELECT * FROM trades WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}"
        )
        rows = await self.pool.fetch(query, *params)
        return [
            Trade(
                id=row["id"],
                timestamp=row["timestamp"],
                symbol=row["symbol"],
                side=row["side"],
                size=row["size"],
                price=row["price"],
                fee=row["fee"],
                pnl=row["pnl"],
                strategy_signal=row["strategy_signal"],
                order_id=row["order_id"],
            )
            for row in rows
        ]

    # --- Positions ---

    async def upsert_position(self, position: Position):
        await self.pool.execute(
            """
            INSERT INTO positions (symbol, size, entry_price, current_price, unrealized_pnl, side, last_updated)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (symbol) DO UPDATE SET
                size = EXCLUDED.size,
                entry_price = EXCLUDED.entry_price,
                current_price = EXCLUDED.current_price,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                side = EXCLUDED.side,
                last_updated = EXCLUDED.last_updated
            """,
            position.symbol,
            position.size,
            position.entry_price,
            position.current_price,
            position.unrealized_pnl,
            position.side,
            position.last_updated,
        )

    async def delete_position(self, symbol: str):
        await self.pool.execute("DELETE FROM positions WHERE symbol = $1", symbol)

    async def get_all_positions(self) -> Dict[str, Position]:
        rows = await self.pool.fetch("SELECT * FROM positions")
        return {
            row["symbol"]: Position(
                id=row["id"],
                symbol=row["symbol"],
                size=row["size"],
                entry_price=row["entry_price"],
                current_price=row["current_price"],
                unrealized_pnl=row["unrealized_pnl"],
                side=row["side"],
                last_updated=row["last_updated"],
            )
            for row in rows
        }

    # --- Signals ---

    async def insert_signal(self, signal: SignalRecord) -> int:
        row = await self.pool.fetchrow(
            """
            INSERT INTO signals (timestamp, symbol, signal_type, target_position, current_position, executed)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            signal.timestamp,
            signal.symbol,
            signal.signal_type,
            signal.target_position,
            signal.current_position,
            signal.executed,
        )
        return row["id"]

    # --- Risk Events ---

    async def insert_risk_event(self, event: RiskEvent) -> int:
        row = await self.pool.fetchrow(
            """
            INSERT INTO risk_events (timestamp, event_type, details, action_taken)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            event.timestamp,
            event.event_type,
            event.details,
            event.action_taken,
        )
        logger.warning(
            "Risk event recorded",
            extra={"event_type": event.event_type, "details": event.details},
        )
        return row["id"]

    # --- Daily Stats ---

    async def get_daily_pnl(self, symbol: Optional[str] = None) -> float:
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if symbol:
            row = await self.pool.fetchrow(
                "SELECT COALESCE(SUM(pnl), 0) AS total FROM trades WHERE timestamp >= $1 AND pnl IS NOT NULL AND symbol = $2",
                today_start,
                symbol,
            )
        else:
            row = await self.pool.fetchrow(
                "SELECT COALESCE(SUM(pnl), 0) AS total FROM trades WHERE timestamp >= $1 AND pnl IS NOT NULL",
                today_start,
            )
        return float(row["total"])

    async def get_trade_count_today(self) -> int:
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM trades WHERE timestamp >= $1",
            today_start,
        )
        return row["cnt"]

    # --- Parameter Snapshots (flat: one row per run with all params) ---

    PARAM_COLUMNS = [
        "SHORT_WINDOW",
        "MED_WINDOW",
        "MED2_WINDOW",
        "LONG_WINDOW",
        "EMA_FAST",
        "EMA_SLOW",
        "RSI_PERIOD",
        "RSI_BULL",
        "RSI_BEAR",
        "RSI_OVERBOUGHT",
        "RSI_OVERSOLD",
        "MACD_FAST",
        "MACD_SLOW",
        "MACD_SIGNAL",
        "BB_PERIOD",
        "FUNDING_LOOKBACK",
        "FUNDING_BOOST",
        "BASE_POSITION_PCT",
        "VOL_LOOKBACK",
        "TARGET_VOL",
        "ATR_LOOKBACK",
        "ATR_STOP_MULT",
        "TAKE_PROFIT_PCT",
        "BASE_THRESHOLD",
        "BTC_OPPOSE_THRESHOLD",
        "PYRAMID_THRESHOLD",
        "PYRAMID_SIZE",
        "CORR_LOOKBACK",
        "HIGH_CORR_THRESHOLD",
        "DD_REDUCE_THRESHOLD",
        "DD_REDUCE_SCALE",
        "COOLDOWN_BARS",
        "MIN_VOTES",
        "THRESHOLD_MIN",
        "THRESHOLD_MAX",
        "BB_COMPRESS_PCTILE",
    ]

    async def insert_param_snapshot(
        self,
        snapshot: ParamSnapshot,
        params: Dict[str, float],
    ) -> int:
        metric_cols = (
            "run_date, sweep_name, period, sharpe, total_return_pct, "
            "max_drawdown_pct, profit_factor, win_rate_pct, "
            "num_trades, ret_dd_ratio, is_best, previous_snapshot_id"
        )
        param_cols = ", ".join(self.PARAM_COLUMNS)
        all_cols = f"{metric_cols}, {param_cols}"
        placeholders = ", ".join(
            ["$" + str(i) for i in range(1, 13 + len(self.PARAM_COLUMNS))]
        )

        values = [
            snapshot.run_date,
            snapshot.sweep_name,
            snapshot.period,
            snapshot.sharpe,
            snapshot.total_return_pct,
            snapshot.max_drawdown_pct,
            snapshot.profit_factor,
            snapshot.win_rate_pct,
            snapshot.num_trades,
            snapshot.ret_dd_ratio,
            snapshot.is_best,
            snapshot.previous_snapshot_id,
        ]
        for col in self.PARAM_COLUMNS:
            values.append(float(params.get(col, 0)))

        row = await self.pool.fetchrow(
            f"INSERT INTO param_snapshots ({all_cols}) VALUES ({placeholders}) RETURNING id",
            *values,
        )
        snapshot_id = row["id"]

        logger.debug(
            "Inserted param snapshot",
            extra={"snapshot_id": snapshot_id},
        )
        return snapshot_id

    def _row_to_snapshot(self, row) -> ParamSnapshot:
        params = {col: float(row[col]) for col in self.PARAM_COLUMNS}
        return ParamSnapshot(
            id=row["id"],
            run_date=row["run_date"],
            sweep_name=row["sweep_name"],
            period=row["period"],
            sharpe=float(row["sharpe"]),
            total_return_pct=float(row["total_return_pct"]),
            max_drawdown_pct=float(row["max_drawdown_pct"]),
            profit_factor=float(row["profit_factor"]),
            win_rate_pct=float(row["win_rate_pct"]),
            num_trades=int(row["num_trades"]),
            ret_dd_ratio=float(row["ret_dd_ratio"]),
            is_best=row["is_best"],
            previous_snapshot_id=row["previous_snapshot_id"],
            params=params,
        )

    async def get_param_history(self, limit: int = 30) -> List[ParamSnapshot]:
        rows = await self.pool.fetch(
            "SELECT * FROM param_snapshots ORDER BY run_date DESC LIMIT $1",
            limit,
        )
        return [self._row_to_snapshot(row) for row in rows]

    async def get_latest_params(self) -> Optional[ParamSnapshot]:
        row = await self.pool.fetchrow(
            "SELECT * FROM param_snapshots WHERE is_best = TRUE ORDER BY run_date DESC LIMIT 1"
        )
        if row is None:
            return None
        return self._row_to_snapshot(row)
