# Equities Adapter

Daily equity trading strategy using the same autoresearch pattern as the crypto version. Uses Yahoo Finance for data (free, no API key required).

## Differences from Crypto Version

| Component | Crypto | Equities |
|---|---|---|
| Data Source | CryptoCompare + Hyperliquid | Yahoo Finance |
| Bar Interval | 1h (hourly) | 1d (daily) |
| Symbols | BTC, ETH, SOL | Any (runtime `--symbols` flag) |
| Leverage | 20x | 2x |
| Fees | 2-5 bps | Commission-free |
| Funding Rate | Yes (crypto perps) | No |
| BTC Correlation Filter | Yes | No |

## Quick Start

```bash
cd equities
uv run prepare.py --symbols AAPL MSFT NVDA    # Download specific symbols
uv run backtest.py --symbols AAPL MSFT NVDA   # Backtest on those symbols
uv run backtest.py                             # Or use defaults (10 diversified tickers)
uv run run_benchmarks.py                       # Run benchmark leaderboard
```

Symbols are chosen at runtime — pass `--symbols` to any script. Missing data is auto-downloaded.

## Configuration

**`prepare.py`:**
- `SYMBOLS` — default tickers (overridden by `--symbols`)
- `TRAIN_START/END`, `VAL_START/END`, `TEST_START/END` — date ranges
- `INITIAL_CAPITAL` — starting capital ($100K)
- `MAX_LEVERAGE` — margin limit (2x for equities)

**`strategy.py`:**
- `ACTIVE_SYMBOLS` — default symbols (overridden by `Strategy(symbols=[...])`)
- `BASE_POSITION_PCT` — position size as fraction of equity
- `MIN_VOTES` — ensemble threshold (3 of 5 signals)
- `ATR_STOP_MULT` — trailing stop multiplier
- Indicator periods: `RSI_PERIOD`, `EMA_FAST/SLOW`, `MACD_*`, etc.

## Strategy Logic

5-signal ensemble with 3/5 majority vote:

1. **Momentum** — short-term return vs dynamic threshold
2. **EMA Crossover** — fast EMA vs slow EMA
3. **RSI** — above/below 50
4. **MACD** — histogram sign
5. **BB Compression** — Bollinger Band width percentile

Exit conditions:
- ATR trailing stop (2.5x ATR from peak)
- RSI mean-reversion (exit longs at RSI > 70, shorts at RSI < 30)
- Signal flip (reverse when opposing ensemble fires)

## Scoring

Same as crypto version:

```
score = sharpe × √(min(trades/50, 1.0)) − drawdown_penalty − turnover_penalty
```

## Using Different Symbols

Just pass `--symbols` at runtime — no config changes needed:

```bash
# Tech stocks
uv run backtest.py --symbols AAPL MSFT GOOGL AMZN META

# Sector ETFs
uv run backtest.py --symbols XLE XLF XLK XLV XLI

# Single stock deep-dive
uv run backtest.py --symbols TSLA
```

Missing data is automatically downloaded from Yahoo Finance on first run.
