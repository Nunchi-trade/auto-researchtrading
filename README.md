# auto-researchtrading

Autonomous trading strategy research on Hyperliquid perpetual futures, using Karpathy's autoresearch pattern for strategy discovery.

## Results

### Autotrader: Score Progression

| Experiment | Score | Sharpe | Max DD | Trades | Key Change |
|-----------|-------|--------|--------|--------|------------|
| Baseline (simple_momentum) | 2.724 | 2.724 | 7.6% | 9081 | Starting point |
| exp15 | 8.393 | 8.823 | 3.1% | 2562 | 5-signal ensemble, 4/5 votes, cooldown |
| exp28 | 9.382 | 9.944 | 3.0% | 2545 | ATR 5.5 trailing stop |
| exp37 | 10.305 | 11.125 | 2.3% | 3212 | BB width compression (6th signal) |
| exp42 | 11.302 | 11.886 | 1.4% | 3024 | Remove funding boost |
| exp46 | 13.480 | 14.015 | 1.4% | 3157 | Remove strength scaling |
| exp56 | 14.592 | 14.666 | 0.7% | 4205 | Cooldown 3 |
| exp66 | 15.718 | 15.849 | 0.7% | 4467 | Simplified momentum |
| exp72 | 19.697 | 20.099 | 0.7% | 6283 | **RSI period 8** |
| exp86 | 19.859 | 20.498 | 0.6% | 7534 | Cooldown 2 |
| **exp102** | **20.634** | **20.634** | **0.3%** | **7605** | RSI 50/50, BB 85, position 0.08 |

**Final score: 20.634** (7.6x improvement over baseline)

### Key Discoveries (in order of impact)

1. **RSI period 8** (+5 points) — Faster RSI is much better for hourly crypto data. Standard 14-period is too slow.
2. **Remove strength scaling** (+1.7 points) — Uniform position sizing beats momentum-weighted sizing.
3. **Simplified momentum** (+0.8 points) — Just `ret_short > threshold`, no multi-timeframe confirmation needed.
4. **BB width compression signal** (+0.9 points) — Bollinger Band width percentile as 6th ensemble signal.
5. **ATR 5.5 trailing stop** (+1 point) — Hold winners much longer than conventional 3.5x ATR.
6. **Simplification** (+2 points total) — Removing pyramiding, funding boost, BTC filter, and correlation filter all improved score.
7. **Position size 0.08** (+0.6 points) — Smaller positions eliminate turnover penalty.

### Biggest Lesson: Simplicity Wins

The strongest gains came from *removing* complexity, not adding it. Features that seem smart in theory (BTC lead-lag filter, correlation-based weight adjustment, momentum strength scaling, pyramiding) all hurt performance in practice. The final strategy is remarkably simple.

## Best Strategy Architecture

**6-signal ensemble with 4/6 majority vote:**

| Signal | Bull Condition | Bear Condition |
|--------|---------------|----------------|
| Momentum | 12h return > dynamic threshold | 12h return < -dynamic threshold |
| Very-short momentum | 6h return > threshold*0.5 | 6h return < -threshold*0.5 |
| EMA crossover | EMA(12) > EMA(26) | EMA(12) < EMA(26) |
| RSI(8) | RSI > 50 | RSI < 50 |
| MACD(12,26,9) | MACD histogram > 0 | MACD histogram < 0 |
| BB compression | BB width < 85th percentile | BB width < 85th percentile |

**Exit conditions:**
- ATR trailing stop: 5.5x ATR from peak
- RSI overbought/oversold: exit longs at RSI > 70, exit shorts at RSI < 30
- Signal flip: reverse position when opposing signal fires

**Key parameters:**
- `BASE_POSITION_PCT = 0.08` — Per-symbol position size as fraction of equity
- `COOLDOWN_BARS = 2` — Minimum bars between exit and re-entry
- `RSI_PERIOD = 8` — Fast RSI for hourly crypto
- `ATR_STOP_MULT = 5.5` — Wide trailing stop to let winners run
- Dynamic momentum threshold adapts to realized volatility

## Autoresearch (LLM Training)

Separate experiment optimizing Karpathy's GPT pretraining script.

**Best result:** `val_bpb = 1.044` (from baseline 1.102)
- Key finding: `WARMUP_RATIO = 0.05` significantly improves training

## Data

- BTC, ETH, SOL hourly OHLCV + funding rates from Hyperliquid
- Validation period: 2024-07-01 to 2025-03-31
- 500-bar history buffer per symbol

## Scoring Formula

```
score = sharpe * sqrt(min(trades/50, 1.0)) - drawdown_penalty - turnover_penalty
drawdown_penalty = max(0, max_drawdown_pct - 15) * 0.05
turnover_penalty = max(0, annual_turnover/capital - 500) * 0.001
Hard cutoffs: <10 trades → -999, >50% drawdown → -999, lost >50% → -999
```

## Branches

- `main` — Base scaffold and data pipeline
- `autotrader/mar10c` — Best autotrader strategy (score 20.634)
- `autoresearch/mar10-opus` — LLM training optimization experiments
