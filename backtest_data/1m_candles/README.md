# 1-Minute Candle Data

1-minute OHLCV + funding rate data for BTC, ETH, SOL, XRP perpetual futures on Hyperliquid.

## Data

| Symbol | Bars | Price Range | Change |
|--------|------|-------------|--------|
| BTC | 2,881 | $70,355 → $68,738 | -2.30% |
| ETH | 2,881 | $2,148.80 → $2,059.80 | -4.14% |
| SOL | 2,881 | $90.44 → $86.36 | -4.50% |
| XRP | 2,881 | $1.41 → $1.36 | -3.91% |

- **Period**: 2026-03-24 22:25 UTC to 2026-03-26 22:26 UTC (48 hours)
- **Interval**: 1 minute
- **Columns**: `timestamp`, `open`, `high`, `low`, `close`, `volume`, `funding_rate`
- **Source**: Hyperliquid `candleSnapshot` + `fundingHistory` REST endpoints

## Files

```
BTC_1m.parquet  (95K)
ETH_1m.parquet  (75K)
SOL_1m.parquet  (99K)
XRP_1m.parquet  (77K)
BTC_1m.csv / ETH_1m.csv / SOL_1m.csv / XRP_1m.csv  (human-readable)
```

## Running the Backtest

```bash
# 1m-tuned strategy (default)
uv run backtest_1m.py

# Compare with hourly strategy on 1m data
uv run backtest_1m.py --strategy strategy

# Download fresh data instead
uv run backtest_1m.py --download --hours 48

# Custom data directory
uv run backtest_1m.py --data-dir ./backtest_data/1m_candles
```

## Backtest Results

> **Disclaimer**: These results are from a single 48h window of bearish market conditions (all 4 assets down 2-4.5%). The sample is too small for statistical significance. The parameter sweep tested ~40 combinations on this window, so overfitting risk is real. Out-of-sample validation (last 24h) showed a small positive return (+$0.77) but with only 16 closed trades. Treat these as preliminary, not conclusive.

### 1m-Tuned Strategy (strategy_1m.py)

Same 6-signal ensemble logic as the hourly strategy, but with **shorter lookback windows** adapted for minute data. These are not time-equivalent scalings — true time-equivalent values (e.g. SHORT_WINDOW=360 for 6h) would require 48h+ of warmup data, leaving no bars to trade on. The lookbacks below are a practical compromise that fits 48h of data while using longer horizons than the naive 1:1 mapping.

| Metric | Value |
|--------|-------|
| Initial capital | $10,000 |
| Bars processed | 2,882 |
| Trades | 133 |
| Closed trades | 54 |
| Win rate | 57.4% |
| Profit factor | 2.90 |
| Gross PnL | $760.67 |
| Net return | +3.59% |
| Max drawdown | 2.35% |
| Final equity | $10,359.03 |
| Runtime | 30.7s |

### Out-of-Sample (last 24h only)

> Note: OOS was validated at POS=0.10. At POS=2.00, OOS return would scale ~20x but so would drawdown. OOS validation should be re-run at the chosen leverage level.

| Metric | Value |
|--------|-------|
| Bars | 1,441 |
| Trades | 47 |
| Closed trades | 16 |
| Win rate | 56.3% (9/16) |
| Profit factor | 2.19 |
| Gross PnL | $8.40 |
| Net return | +0.008% |
| Max drawdown | 0.10% |
| Final equity | $10,000.77 |

### Hourly Strategy on 1m Data (strategy.py — untuned, for comparison)

| Metric | Value |
|--------|-------|
| Trades | 3,307 |
| Closed trades | 1,472 |
| Win rate | 62.3% |
| Profit factor | 4.97 |
| Gross PnL | $180.24 |
| Net return | -1.82% |
| Max drawdown | 1.85% |
| Final equity | $9,817.85 |

### Leverage Scaling

The strategy's edge scales linearly with position size. Return/DD ratio is nearly constant (~1.53) across all leverage levels. There is no "golden pocket" — higher leverage amplifies both returns and drawdowns proportionally.

| POS (exposure) | Leverage | Return | Drawdown | Ret/DD | Final Equity |
|-----------------|----------|--------|----------|--------|-------------|
| 0.25 | 1x | +0.45% | 0.30% | 1.50 | $10,045 |
| 0.50 | 2x | +0.90% | 0.60% | 1.51 | $10,090 |
| 1.00 | 4x | +1.80% | 1.19% | 1.51 | $10,180 |
| **2.00** | **8x** | **+3.59%** | **2.35%** | **1.53** | **$10,359** |
| 3.00 | 12x | +5.38% | 3.48% | 1.54 | $10,538 |
| 5.00 | 20x | +8.92% | 5.68% | 1.57 | $10,892 |

### Tuning Summary

The hourly strategy is directionally profitable (62% win rate, $180 gross PnL) but generates 3,307 trades in 48h — the fees ($355+) wipe out the edge. Adapting for 1m required:

1. **Shorter lookbacks** to fit available data (see parameter table below — these are shorter than true time-equivalent values)
2. **Wider ATR trailing stop**: 5.5→6.5 to hold positions longer and capture more of each move
3. **Longer cooldown**: 2→60 bars (1h) to prevent rapid re-entry after exits
4. **Aggressive position sizing**: 0.08→2.00 (8x leverage) to scale the edge

The key finding: **MIN_VOTES=4 is the critical filter**. Dropping to 3 votes creates 900+ trades and kills returns. The 4/6 majority filter is what makes 1m viable. Position size is the primary lever for absolute returns — the risk-adjusted edge (ret/DD) is flat across all sizes.

### Parameter Comparison

Hourly values are in hourly bars. 1m values are in minute bars. "True equiv" is what a literal 60x scaling would produce.

| Parameter | Hourly | 1m-Tuned | True equiv (60x) | Actual ratio |
|-----------|--------|----------|-------------------|--------------|
| SHORT_WINDOW | 6 (6h) | 60 (1h) | 360 (6h) | 0.17x |
| MED_WINDOW | 12 (12h) | 240 (4h) | 720 (12h) | 0.33x |
| MED2_WINDOW | 24 (24h) | 480 (8h) | 1440 (24h) | 0.33x |
| LONG_WINDOW | 36 (36h) | 720 (12h) | 2160 (36h) | 0.33x |
| EMA_FAST / SLOW | 7 / 26 | 60 / 240 | 420 / 1560 | 0.15x |
| RSI_PERIOD | 8 (8h) | 60 (1h) | 480 (8h) | 0.13x |
| MACD | 14/23/9 | 120/240/60 | 840/1380/540 | 0.14x |
| BB_PERIOD | 7 (7h) | 60 (1h) | 420 (7h) | 0.14x |
| ATR_LOOKBACK | 24 (24h) | 120 (2h) | 1440 (24h) | 0.08x |
| ATR_STOP_MULT | 5.5 | **6.5** | 5.5 | 1.18x |
| COOLDOWN_BARS | 2 (2h) | **60** (1h) | 120 (2h) | 0.50x |
| BASE_POSITION_PCT | 0.08 | **2.00** | 0.08 | 25.00x |

### Equity Curve (1m-tuned, full 48h, POS=2.00)

```
  0%: $  10,000.00
 25%: $   10,000.00
 50%: $  10,047.72
 75%: $  10,377.33
100%: $  10,359.03
```

### Per-Trade Stats (1m-tuned, closed trades, POS=2.00)

| Metric | Value |
|--------|-------|
| Avg PnL | $14.09 |
| Best PnL | $72.51 |
| Worst PnL | -$49.65 |

### Backtest Configuration

- LOOKBACK_BARS: 1,500 (25h of history buffer)
- Funding scaled for 1m bars: divided by 480 (8h / 1min)
- Fees: 5bps taker + 1bps slippage per trade
- Position sizing: `equity * 2.00 * weight` per signal (equal 0.25 weight across 4 symbols, 8x max leverage)
- Per-minute Sharpe is reported raw (not annualized); annualizing 48h of minute returns would be statistically meaningless
