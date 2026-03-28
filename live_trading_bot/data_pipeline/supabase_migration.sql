-- Trading Bot Database Migration for Supabase
-- Run this in: Supabase Dashboard → SQL Editor → New Query
--
-- This creates all required tables with PostgreSQL-native types.
-- The bot connects via asyncpg/psycopg2 using the service_role connection string.
-- service_role key bypasses RLS, so policies are permissive.

-- ============================================================================
-- TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    fee DOUBLE PRECISION NOT NULL,
    pnl DOUBLE PRECISION,
    strategy_signal TEXT,
    order_id TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT UNIQUE NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    current_price DOUBLE PRECISION NOT NULL,
    unrealized_pnl DOUBLE PRECISION NOT NULL,
    side TEXT NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    target_position DOUBLE PRECISION NOT NULL,
    current_position DOUBLE PRECISION NOT NULL,
    executed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS risk_events (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    details TEXT NOT NULL,
    action_taken TEXT
);

-- param_snapshots: one row per optimization run (metrics only)
CREATE TABLE IF NOT EXISTS param_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_date TIMESTAMPTZ NOT NULL,
    sweep_name TEXT NOT NULL DEFAULT '',
    sharpe DOUBLE PRECISION NOT NULL,
    total_return_pct DOUBLE PRECISION NOT NULL,
    max_drawdown_pct DOUBLE PRECISION NOT NULL,
    profit_factor DOUBLE PRECISION NOT NULL,
    win_rate_pct DOUBLE PRECISION NOT NULL,
    num_trades INTEGER NOT NULL,
    ret_dd_ratio DOUBLE PRECISION NOT NULL,
    is_best BOOLEAN NOT NULL DEFAULT FALSE,
    previous_snapshot_id BIGINT REFERENCES param_snapshots(id) ON DELETE SET NULL
);

-- param_values: one row per parameter per snapshot (36 rows per run)
CREATE TABLE IF NOT EXISTS param_values (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES param_snapshots(id) ON DELETE CASCADE,
    param_name TEXT NOT NULL,
    param_value DOUBLE PRECISION NOT NULL,
    UNIQUE(snapshot_id, param_name)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_risk_events_timestamp ON risk_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_param_snapshots_run_date ON param_snapshots(run_date);
CREATE INDEX IF NOT EXISTS idx_param_snapshots_is_best ON param_snapshots(is_best) WHERE is_best = TRUE;
CREATE INDEX IF NOT EXISTS idx_param_values_snapshot_id ON param_values(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_param_values_param_name ON param_values(param_name);

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================================

ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE param_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE param_values ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all access" ON trades FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all access" ON positions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all access" ON signals FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all access" ON risk_events FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all access" ON param_snapshots FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all access" ON param_values FOR ALL USING (true) WITH CHECK (true);
