# equities-autotrader

Autonomous trading strategy research on US equities (daily bars).

## Context

This project adapts the autoresearch pattern for equity strategy discovery on daily bars. Symbols are chosen at runtime — the system works with any ticker available on Yahoo Finance.

Your job: **discover novel daily-timeframe strategies** that outperform the benchmarks.

## Current Leaderboard (your target to beat)

```
RANK  STRATEGY             SCORE     SHARPE   RETURN    MAX_DD   TRADES
1.    ensemble (ours)      5.582     5.582    +127.0%   1.8%     1654     ← CURRENT BEST
2.    simple_momentum      1.447     1.447    +23.0%    5.8%     262      ← BASELINE TO BEAT
3.    trend_following      1.358     1.698    +41.4%    6.8%     32
4.    buy_and_hold         0.960     2.147    +102.8%   12.4%    10
5.    mean_reversion       0.365     0.365    +4.5%     9.4%     477
```

## Setup

To set up a new experiment:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `eq-mar21`). The branch `equities-autotrader/<tag>` must not already exist.
2. **Create the branch**: `git checkout -b equities-autotrader/<tag>`
3. **Read the in-scope files**: `equities/prepare.py`, `equities/strategy.py`, `equities/backtest.py`, this file.
4. **Choose symbols**: decide which tickers to experiment on (e.g. `SPY QQQ AAPL NVDA`).
5. **Verify data exists**: `ls ~/.cache/equities-autotrader/data/` — missing symbols are auto-downloaded.
6. **Initialize results.tsv**: `echo -e "commit\tscore\tsharpe\tmax_dd\tstatus\tdescription" > equities/results.tsv`
7. **Confirm and go**.

## Experimentation

Each experiment backtests daily equity data. Symbols are passed at runtime.

Launch:
```bash
cd equities && uv run backtest.py --symbols SPY QQQ AAPL NVDA
```

Or use defaults:
```bash
cd equities && uv run backtest.py
```

**What you CAN do:**
- Modify `equities/strategy.py` — this is the only file you edit. Everything is fair game.

**What you CANNOT do:**
- Modify `prepare.py`, `backtest.py`, or anything in `benchmarks/`.
- Install new packages. Only numpy, pandas, scipy, and standard library.
- Look at test set data.

**The goal: get the highest `score`.** Higher is better.

## Output format

```
grep "^score:" run.log
```

## Results TSV

```
commit	score	sharpe	max_dd	status	description
```

## The experiment loop

LOOP FOREVER:

1. Look at git state
2. Modify `equities/strategy.py` with an experimental idea
3. git commit
4. `cd equities && uv run backtest.py --symbols <YOUR_SYMBOLS> > run.log 2>&1`
5. `grep "^score:\|^sharpe:\|^max_drawdown_pct:" run.log`
6. If empty → crashed. `tail -n 50 run.log`, fix or skip.
7. Record in equities/results.tsv (untracked)
8. If score IMPROVED (higher than best so far): keep
9. If score equal or worse: `git reset --hard HEAD~1`

## Strategy Research Directions (Equities-Specific)

### Tier 1 — Most Likely to Improve Score
- **Reduce MIN_VOTES**: 4/5 is too strict for daily bars; try 3/5
- **Inverse-vol position sizing**: equalize risk contribution across symbols
- **Wider ATR stops**: daily ATR is already large; tune the multiplier
- **Sector rotation**: overweight sectors with strongest momentum
- **Cross-symbol relative momentum**: rank symbols, go long top, short bottom

### Tier 2 — Worth Exploring
- **TLT as risk filter**: TLT direction indicates risk-on/risk-off regime
- **Weekly vs daily momentum**: 5-day and 20-day returns as separate signals
- **Earnings avoidance**: reduce exposure when vol spikes (proxy for earnings)
- **Correlation-regime switching**: different strategies for high/low correlation
- **Volume profile**: unusually high volume confirms breakouts

### Tier 3 — Novel / Experimental
- **Sector momentum**: compute sector-level signals from ETFs, apply to stocks
- **Pairs trading**: long outperformer / short underperformer within sector
- **Calendar effects**: day-of-week or month-of-year seasonality
- **Adaptive ensemble weights**: weight signals by recent predictive accuracy
- **Volatility term structure**: short-term vs long-term realized vol divergence

## Data Available

- Any US equity or ETF via Yahoo Finance (auto-downloaded)
- Daily OHLCV bars
- Val period: 2023-01-01 to 2024-12-31 (~504 trading days)
- History buffer: last 250 bars via `bar_data[symbol].history` DataFrame
- Columns: timestamp, open, high, low, close, volume

## Key Differences from Crypto

- **Daily bars** (not hourly): signals are slower, need wider thresholds and stops
- **No funding rates**: pure directional trading
- **Lower leverage**: 2x max, so position sizing matters more
- **More symbols**: genuine sector diversification (crypto is BTC/ETH/SOL all correlated)
- **Commission-free**: can trade frequently without cost penalty
- **252 trading days/year** (not 8760 hours)

## Scoring Formula (from prepare.py)

```
score = sharpe * sqrt(trade_count_factor) - drawdown_penalty - turnover_penalty
trade_count_factor = min(num_trades / 50, 1.0)
drawdown_penalty = max(0, max_drawdown_pct - 15) * 0.05
turnover_penalty = max(0, annual_turnover/capital - 500) * 0.001
Hard cutoffs: <10 trades → -999, >50% drawdown → -999, lost >50% → -999
```

## NEVER STOP

Once the experiment loop has begun, do NOT pause to ask the human if you should continue. You are autonomous. If you run out of ideas, think harder. The loop runs until interrupted.
