"""Active parameters — single source of truth for live trading strategy params.

One row per tuning period in the active_params table.  The live strategy
reads from this table instead of a JSON config file.
"""

import logging
import os
import struct
import time
import uuid

import psycopg2

logger = logging.getLogger(__name__)


def generate_uuid7() -> str:
    """Generate a UUIDv7 string (time-ordered, millisecond precision)."""
    ms = int(time.time() * 1000)
    rand_bytes = os.urandom(10)

    # Build 16 bytes: 6 (timestamp) + 2 (version+rand) + 8 (variant+rand)
    time_bytes = ms.to_bytes(6, "big")
    byte6 = (0x7 << 4) | (rand_bytes[0] & 0x0F)  # version=0111 + 4 random bits
    byte7 = rand_bytes[1]  # 8 random bits
    byte8 = (0x2 << 6) | (rand_bytes[2] & 0x3F)  # variant=10 + 6 random bits

    uuid_bytes = time_bytes + bytes([byte6, byte7, byte8]) + rand_bytes[3:10]
    return str(uuid.UUID(bytes=uuid_bytes))


METRIC_COLUMNS = [
    "sharpe",
    "total_return_pct",
    "max_drawdown_pct",
    "profit_factor",
    "win_rate_pct",
    "num_trades",
    "ret_dd_ratio",
]

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

INT_PARAMS = {
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
    "VOL_LOOKBACK",
    "ATR_LOOKBACK",
    "COOLDOWN_BARS",
    "MIN_VOTES",
    "CORR_LOOKBACK",
    "BB_COMPRESS_PCTILE",
    "num_trades",
}

_ALL_COLUMNS = ["id", "period", "sweep_name"] + METRIC_COLUMNS + PARAM_COLUMNS


def _coerce(col: str, val):
    if col in INT_PARAMS:
        return int(val)
    return float(val)


def save_active_params(
    db_url: str,
    period: str,
    sweep_name: str,
    metrics: dict,
    params: dict,
) -> str:
    row_id = generate_uuid7()

    cols = ["id", "period", "sweep_name"]
    vals: list = [row_id, period, sweep_name]

    for c in METRIC_COLUMNS:
        cols.append(c)
        vals.append(_coerce(c, metrics[c]))

    for c in PARAM_COLUMNS:
        cols.append(c)
        vals.append(_coerce(c, params[c]))

    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    update_set = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c not in ("id", "period")
    )

    sql = (
        f"INSERT INTO active_params ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (period) DO UPDATE SET {update_set}"
    )

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, vals)
            conn.commit()
    except Exception:
        logger.exception("Failed to upsert active_params for period=%s", period)
        raise

    return row_id


def load_active_params(db_url: str) -> dict | None:
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM active_params ORDER BY created_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row is None:
                    return None
                col_names = [desc[0] for desc in cur.description]
    except Exception:
        logger.exception("Failed to load active_params")
        raise

    raw = {k.upper(): v for k, v in zip(col_names, row)}

    result: dict = {}
    for c in PARAM_COLUMNS:
        result[c] = _coerce(c, raw[c.upper()])
    for c in METRIC_COLUMNS:
        result[c] = _coerce(c, raw[c.upper()])
    result["period"] = raw.get("PERIOD", raw.get("period", ""))
    result["sweep_name"] = raw.get("SWEEP_NAME", raw.get("sweep_name", ""))

    return result
