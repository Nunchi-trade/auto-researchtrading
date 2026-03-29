# Running the Trading Bot

## Prerequisites

- **Python 3.10+** with [uv](https://docs.astral.sh/uv/)
- **Hyperliquid account** with funded wallet (live only)
- **Private key** from your Hyperliquid wallet

## Installation

Dependencies are in the repo's `pyproject.toml`. From the repo root:

```bash
uv sync
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Required Variables

| Variable | Description | Example |
|---|---|---|
| `HYPERLIQUID_PRIVATE_KEY` | Your Ethereum private key (with or without `0x` prefix) | `0xabc123...` |
| `DRY_RUN` | `true` = simulated trading, `false` = real money | `true` |

### Trading Variables

| Variable | Default | Description |
|---|---|---|
| `TRADING_PAIRS` | `BTC,ETH,SOL,XRP` | Comma-separated symbols to trade |
| `MAX_LEVERAGE` | `20` | Max leverage per position |
| `MAX_POSITION_PCT` | `0.30` | Max position as fraction of equity |
| `DAILY_LOSS_LIMIT_PCT` | `0.05` | Kill switch at 5% daily loss |
| `BAR_INTERVAL` | `15m` | Candle interval (determines which strategy loads) |
| `STRATEGY_MODULE` | *(auto)* | Override strategy module path. If unset, derived from `BAR_INTERVAL` |

### Strategy Selection

`BAR_INTERVAL` auto-selects the matching strategy:

| BAR_INTERVAL | Strategy Module | Backtest Return | Status |
|---|---|---|---|
| `15m` | `strategies.strategy_15m` | +646% (tuned) | **Recommended** |
| `5m` | `strategies.strategy_5m` | +10.6% (baseline) | Untuned |
| `1m` | `strategies.strategy_1m` | +3.6% (tuned) | Thin edge |
| `1h` | `_bt_strategy` | +130% | Upstream hourly |

### Dry Run Settings

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN_INITIAL_CAPITAL` | `10000` | Starting capital for simulated portfolio |

### Optional: Alerts

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for trade/error alerts |
| `TELEGRAM_CHAT_ID` | Telegram chat ID to receive alerts |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL for alerts |

Alerts are optional. The bot works without them — it just won't send notifications.

---

## Dry Run

Dry run simulates trading against live market data without sending real orders. It uses the same strategy, data feed, and risk checks as live mode. No capital is at risk.

### Start

```bash
cd live_trading_bot
DRY_RUN=true python3 bot.py
```

Or set `DRY_RUN=true` in `.env` and just run:

```bash
cd live_trading_bot
python3 bot.py
```

### What Happens

1. Loads your private key (used to connect to Hyperliquid's public API — no orders placed)
2. Connects to Hyperliquid via WebSocket for live candle and funding data
3. Builds bar history (15m strategy needs ~250 bars = ~62.5 hours to warm up)
4. Runs the strategy on each new bar
5. Logs signals, positions, and equity to `logs/bot.log` and `trading_bot.db`
6. **Does not** place any orders or interact with your wallet balance

### Monitoring

```bash
# Tail logs
tail -f logs/bot.log

# Check the database
sqlite3 trading_bot.db "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;"
sqlite3 trading_bot.db "SELECT * FROM signal_records ORDER BY timestamp DESC LIMIT 10;"
```

### Stop

`Ctrl+C`. The bot catches SIGINT and shuts down gracefully (closes WebSocket, database, alert connections).

---

## Live Trading

Live trading places real orders on Hyperliquid with real capital. Make sure you understand the risks before proceeding.

### Pre-Flight Checklist

1. **Dry run passed** — Run dry run for at least 24-48 hours. Verify signals look correct and the bot handles reconnections gracefully.
2. **Funded wallet** — Deposit USDC on Hyperliquid (Arbitrum). The bot uses your wallet balance as margin.
3. **Private key has funds** — The private key in `.env` must control the wallet holding your trading capital.
4. **Leverage is set correctly** — `MAX_LEVERAGE=20` for the 15m strategy (POS=2.00 means each position is 2x equity). Confirm this matches your risk tolerance.
5. **Alerts configured** — Set up at least Telegram or Discord alerts so you get notified of trades and errors.
6. `.env` is correct** — `DRY_RUN=false` (or unset, defaults to false), `BAR_INTERVAL=15m`.

### Start

```bash
cd live_trading_bot
DRY_RUN=false python3 bot.py
```

Or set in `.env`:
```
DRY_RUN=false
```

### What Happens

1. Loads your private key and connects to Hyperliquid
2. Sets leverage to `MAX_LEVERAGE` on all trading pairs
3. Connects via WebSocket for live data
4. Runs the strategy on each new bar
5. **Places real orders** through Hyperliquid's API (market orders, IOC)
6. Logs everything to `logs/bot.log` and `trading_bot.db`

### Monitoring

```bash
# Tail logs (JSON format)
tail -f logs/bot.log

# Recent trades
sqlite3 trading_bot.db "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;"

# Recent signals
sqlite3 trading_bot.db "SELECT * FROM signal_records ORDER BY timestamp DESC LIMIT 10;"

# Trade count today
sqlite3 trading_bot.db "SELECT COUNT(*) FROM trades WHERE date(timestamp) = date('now');"

# Daily PnL
sqlite3 trading_bot.db "SELECT SUM(pnl) FROM trades WHERE date(timestamp) = date('now');"
```

### Stop

`Ctrl+C`. The bot catches SIGINT and shuts down gracefully. Open positions remain open — they are NOT closed automatically on shutdown. You can close them manually on Hyperliquid.

---

## Backtesting

Run historical backtests against saved candle data to evaluate strategy performance before risking capital.

### From `live_trading_bot/` directory

```bash
cd live_trading_bot

# 15m strategy (recommended)
python3 backtest/backtest_interval.py --interval 15m --strategy strategies.strategy_15m

# 5m strategy
python3 backtest/backtest_interval.py --interval 5m --strategy strategies.strategy_5m

# 1m strategy
python3 backtest/backtest_interval.py --interval 1m --strategy strategies.strategy_1m

# Download fresh data then backtest
python3 backtest/backtest_interval.py --interval 15m --strategy strategies.strategy_15m --download --hours 1080
```

### Parameter Tuning

```bash
cd live_trading_bot

# Quick commands via Makefile (recommended)
make tune           # Daily tune: 8 workers, 4x subsampled screening, full revalidation, OOS
make tune-full      # Same but no subsampling — slower, more thorough
make tune-fast      # Heavy subsampling (8x) for fast iteration
make tune-no-oos    # Skip out-of-sample validation
make download       # Download 15m candle data only (no tuning)

# Or run directly:
python3 backtest/tune_15m.py --phase all

# Individual phases
python3 backtest/tune_15m.py --phase single     # High-impact params
python3 backtest/tune_15m.py --phase secondary   # Secondary params
python3 backtest/tune_15m.py --phase multi       # Multi-param grid
python3 backtest/tune_15m.py --phase oos         # OOS validation only

# Custom parameter OOS test
python3 backtest/tune_15m.py --phase oos --oos-params '{"ATR_STOP_MULT": 8.0, "MIN_VOTES": 5}'
```

**How tuning works:** The pipeline runs single-parameter sweeps → secondary sweeps → forward stepwise accumulation → adaptive multi-parameter grid → OOS validation. All results are saved to `param_snapshots` (audit trail). The single best result is saved to `active_params` — the strategy reads from this table at startup as its source of truth. No JSON config files involved.

| Make target | Subsample | OOS | Speed | Use case |
|---|---|---|---|---|
| `make tune` | 4x | Yes | ~10 min | **Daily production run** |
| `make tune-full` | none | Yes | ~40 min | Weekend deep tune |
| `make tune-fast` | 8x | Yes | ~5 min | Quick sanity check |
| `make tune-no-oos` | 4x | No | ~8 min | Skip validation when iterating |
| `make download` | — | — | ~15s | Just refresh candle data |

See `results.md` for full tuning results and strategy comparison.

---

## Troubleshooting

### "HYPERLIQUID_PRIVATE_KEY not set"
Private key is required even in dry run (used for API authentication). Set it in `.env` or as an environment variable.

### "ModuleNotFoundError: No module named 'config'"
Make sure you're running from inside `live_trading_bot/`, not the repo root. The bot uses relative imports within its directory.

### Bot starts but no signals appear
The strategy needs warm-up time. The 15m strategy needs ~250 bars (~62 hours) of history before it starts generating signals. Wait for the history buffer to fill.

### Reconnection issues
The bot auto-reconnects on WebSocket disconnect with exponential backoff (1s → 60s max). If it can't reconnect after 60s, it logs an error and keeps trying.

### Database locked
Only one bot instance should use `trading_bot.db` at a time. If you see "database is locked" errors, another process is using the file.

### Ctrl+C doesn't stop the bot
This is a known issue with the websockets library blocking on read. Press Ctrl+C twice, or kill the process: `pkill -f "python3 bot.py"`.
