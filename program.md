# autotrader

Historical note: this file describes the original Hyperliquid-only autoresearch loop. For the current repository-wide `autoresearch` flow that also covers Upbit spot and Upbit MTF research, start with `CLAUDE.md` and `docs/README.md`.

Autonomous trading strategy research on Hyperliquid perpetual futures.

## Context

This project adapts Karpathy's autoresearch pattern for trading strategy discovery.
The owner (Nunchi) has existing production strategies that were designed for **tick-level market making** (20-second intervals). Those strategies underperform when ported to **hourly directional trading** on this backtest harness.

Your job: **discover novel hourly-timeframe strategies** that outperform both the simple baseline AND the existing production strategies.

## Current Leaderboard (your target to beat)

```
RANK  STRATEGY             SCORE     SHARPE   RETURN    MAX_DD   TRADES
1.    simple_momentum      2.724     2.724    +42.6%    7.6%     9081     ← BASELINE TO BEAT
2.    funding_arb          -0.191    -0.191   -1.3%     9.4%     1403
3.    regime_mm            -0.322    -0.322   -3.1%     11.2%    12854
4.    mean_reversion       -3.964    -3.380   -26.2%    26.7%    3185
5.    avellaneda_mm        -999      (no trades — MM strategy doesn't port to hourly)
6.    momentum_breakout    -999      (no trades — breakout too tight for hourly)
```

The baseline momentum strategy scores 2.724. **Your goal is to beat 2.724.**

## Existing Strategy Concepts (from production codebase)

These concepts are proven in live trading at tick-level. Adapt them for hourly:

1. **Avellaneda-Stoikov**: reservation_price = mid - q * gamma * sigma^2 * T. Skew quotes based on inventory. The key insight: use inventory-awareness to size positions.
2. **Vol regime classification**: Bin vol into 4 regimes (low/normal/high/extreme) with hysteresis. Adjust size and stops per regime. Immediate upshift, delayed downshift.
3. **Funding rate carry**: Short when funding high (shorts get paid), long when negative. The carry component is real P&L on Hyperliquid perps.
4. **Cross-venue funding arb**: When HL funding diverges from median, bias quotes. Asymmetric sizing: favor the side collecting premium.
5. **Momentum breakout**: Enter on price breaking N-period range with volume confirmation. Trailing stops.
6. **Risk multipliers**: Vol bin → size multiplier. Drawdown bin → spread/stop multiplier. Green/yellow/orange/red zones.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar10`). The branch `autotrader/<tag>` must not already exist.
2. **Create the branch**: `git checkout -b autotrader/<tag>` from current master.
3. **Read the in-scope files**: `prepare.py`, `strategy.py`, `backtest.py`, this file.
4. **Verify data exists**: `ls ~/.cache/autotrader/data/`
5. **Initialize results.tsv**: `echo -e "commit\tscore\tsharpe\tmax_dd\tstatus\tdescription" > results.tsv`
6. **Confirm and go**.

## Experimentation

Each experiment runs a backtest on historical Hyperliquid perp data (BTC, ETH, SOL, hourly bars, Jul 2024 - Mar 2025). Launch: `uv run backtest.py`.

**What you CAN do:**
- Modify `strategy.py` — this is the only file you edit. Everything is fair game.

**What you CANNOT do:**
- Modify `prepare.py`, `backtest.py`, or anything in `benchmarks/`.
- Install new packages. Only numpy, pandas, scipy, and standard library.
- Look at test set data.

**The goal: get the highest `score`.** Higher is better. Baseline is 2.724.

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
2. Modify `strategy.py` with an experimental idea
3. git commit
4. `uv run backtest.py > run.log 2>&1`
5. `grep "^score:\|^sharpe:\|^max_drawdown_pct:" run.log`
6. If empty → crashed. `tail -n 50 run.log`, fix or skip.
7. Record in results.tsv (untracked)
8. If score IMPROVED (higher than best so far): keep
9. If score equal or worse: `git reset --hard HEAD~1`

## Strategy Research Directions

Start with these high-probability ideas:

### Tier 1 — Most Likely to Improve Score
- **Add SOL with lower weight** — diversification should help Sharpe
- **Vol-regime adaptive sizing** — reduce positions in high vol, increase in low vol (proven concept from production)
- **Multi-timeframe momentum** — require 12h, 24h, 48h agreement before entry
- **ATR-based trailing stops** — current fixed stops are suboptimal
- **Funding carry overlay** — add carry component on top of momentum

### Tier 2 — Worth Exploring
- **EMA crossover instead of raw momentum** — smoother signals, fewer whipsaws
- **Cross-asset lead-lag** — BTC momentum predicts ETH/SOL 1-6h later
- **Dynamic threshold** — adjust momentum entry threshold by recent vol
- **Inverse vol position sizing** — proven in production risk framework
- **Ensemble voting** — combine 3+ signals, only enter when majority agree

### Tier 3 — Radical / Novel
- **Pure mean reversion on funding rate** — trade the mean reversion of funding itself
- **Correlation regime switching** — different strategies for high/low BTC-ETH correlation
- **Pairs trading** — long ETH/short BTC (or vice versa) on relative value
- **Time-of-day patterns** — are there hourly seasonality patterns?
- **Volatility breakout** — enter when realized vol breaks above/below its own SMA
- **Machine learning lite** — rolling linear regression of features → direction

## Data Available

- BTC, ETH, SOL hourly OHLCV + funding rates
- Val period: 2024-07-01 to 2025-03-31
- History buffer: last 500 bars via `bar_data[symbol].history` DataFrame
- Columns: timestamp, open, high, low, close, volume, funding_rate

## Scoring Formula (from prepare.py)

```
score = sharpe * sqrt(trade_count_factor) - drawdown_penalty - turnover_penalty
trade_count_factor = min(num_trades / 50, 1.0)
drawdown_penalty = max(0, max_drawdown_pct - 15) * 0.05
turnover_penalty = max(0, annual_turnover/capital - 500) * 0.001
Hard cutoffs: <10 trades → -999, >50% drawdown → -999, lost >50% → -999
```

## Council Mode (adversarial convergence-breaking)

After **5 consecutive experiments with no improvement**, enter Council Mode to break out of local optima.

### Step 1: Generate Diverse Proposals

Read current `strategy.py` and full results.tsv. Generate **3-5 proposals**, each from a distinct philosophy (change only one parameter per proposal):
- **Simplification** — remove a component; test if performance holds
- **Contrarian** — opposite of current approach (momentum → mean-reversion, etc.)
- **Regime-shift** — what would change if market conditions shifted?
- **Scale-change** — different timeframe, asset weighting, or position size
- **Radical** — completely different approach to the problem

### Step 2: Anonymize & Peer Review

Label as "Proposal A/B/C/D/E". Evaluate each: pros, cons, overfitting risk, regime robustness, complexity cost. Output `FINAL RANKING: 1. Proposal X, 2. Proposal Y...`

### Step 3: Execute & Cascade

- Apply only #1. Run eval, keep/discard as normal.
- If #1 fails → try #2, then #3.
- If ALL fail → log `COUNCIL_PASS: strategy survived adversarial review (N proposals tested)` in results.tsv. Resume with fresh research directions.
- If any succeeds → log `COUNCIL_ACCEPT: Proposal X adopted (philosophy)` in results.tsv. Continue from new baseline.

### Council Log

Maintain `council_log.md` (append-only). Each entry:
```
## Council Session #N — Experiment <exp> (score: <value>)
Trigger: 5 no-improvement experiments (<start> through <end>)
Proposals: A=Simplification(...), B=Contrarian(...), C=Radical(...)
Ranking: 1. B, 2. A, 3. C — rationale: ...
Outcome: COUNCIL_ACCEPT Proposal B / COUNCIL_PASS
```

## NEVER STOP

Once the experiment loop has begun, do NOT pause to ask the human if you should continue. You are autonomous. If you run out of ideas, think harder. The loop runs until interrupted.
