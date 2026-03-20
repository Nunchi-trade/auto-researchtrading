# Equities Adapter

Daily equity trading strategy using the same autoresearch pattern as the crypto version. Uses Yahoo Finance for data (free, no API key required).

## Differences from Crypto Version

| Component | Crypto | Equities |
|---|---|---|
| Data Source | CryptoCompare + Hyperliquid | Yahoo Finance |
| Bar Interval | 1h (hourly) | 1d (daily) |
| Symbols | BTC, ETH, SOL | SPY, QQQ, AAPL, MSFT, NVDA |
| Leverage | 20x | 2x |
| Fees | 2-5 bps | Commission-free |
| Funding Rate | Yes (crypto perps) | No |
| BTC Correlation Filter | Yes | No |

## Quick Start

```bash
cd equities
uv run prepare.py          # Download data from Yahoo Finance
uv run backtest.py         # Run backtest on validation data
```

## Configuration

Edit constants at the top of each file:

**`prepare.py`:**
- `SYMBOLS` — tickers to trade
- `TRAIN_START/END`, `VAL_START/END`, `TEST_START/END` — date ranges
- `INITIAL_CAPITAL` — starting capital
- `MAX_LEVERAGE` — margin limit (2x for equities)

**`strategy.py`:**
- `ACTIVE_SYMBOLS` — symbols to include in strategy
- `BASE_POSITION_PCT` — position size as fraction of equity
- `MIN_VOTES` — ensemble threshold (4 of 5 signals)
- `ATR_STOP_MULT` — trailing stop multiplier
- Indicator periods: `RSI_PERIOD`, `EMA_FAST/SLOW`, `MACD_*`, etc.

## Strategy Logic

5-signal ensemble with 4/5 majority vote:

1. **Momentum** — short-term return vs dynamic threshold
2. **EMA Crossover** — fast EMA vs slow EMA
3. **RSI** — above/below 50
4. **MACD** — histogram sign
5. **BB Compression** — Bollinger Band width percentile

Exit conditions:
- ATR trailing stop (3x ATR from peak)
- RSI mean-reversion (exit longs at RSI > 70, shorts at RSI < 30)
- Signal flip (reverse when opposing ensemble fires)

## Scoring

Same as crypto version:

```
score = sharpe × √(min(trades/50, 1.0)) − drawdown_penalty − turnover_penalty
```

## Adapting for Other Markets

To use different symbols:
1. Edit `ACTIVE_SYMBOLS` in `strategy.py`
2. Edit `SYMBOLS` in `prepare.py`
3. Run `rm -rf ~/.cache/equities-autotrader` to clear cached data
4. Run `uv run prepare.py` to download new data

For futures (ES, NQ, CL), Yahoo Finance coverage is limited. Consider:
- Using daily bars (hourly futures data requires paid providers)
- Adjusting `MAX_LEVERAGE` (futures margin is different)
- Adding futures-specific logic (roll dates, contract months)
