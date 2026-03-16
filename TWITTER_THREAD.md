# Twitter Thread: Autoresearch Trading

## Tweet 1 (Hook) — attach `1_score_evolution.png`

Inspired by @kaboratsky's autoresearch, we gave Claude a trading strategy and told it to never stop improving.

251 experiments later, zero human intervention:

Sharpe: 2.7 → 21.4
Max drawdown: 7.6% → 0.3%
Return: +130% on 9mo of hourly crypto

The AI taught itself to be a quant. Thread:

---

## Tweet 2 (The Setup) — attach `2_before_after.png`

The loop is dead simple:

1. Modify strategy.py
2. Git commit
3. Backtest against 9mo of BTC/ETH/SOL hourly data
4. Score it (Sharpe-based with DD + turnover penalties)
5. If better → keep. If worse → git reset --hard
6. Repeat forever

RunPod A100. No human in the loop. Just pure evolutionary pressure.

---

## Tweet 3 (The Surprise) — attach `3_simplification.png`

The biggest discovery wasn't what the AI added — it was what it removed.

Phase 1-3: Built a complex ensemble. Pyramiding, funding carry, BTC lead-lag filters, correlation regime detection, vol-adaptive sizing...

Phase 4: "The Great Simplification." It systematically deleted every clever feature. Each removal IMPROVED performance.

Removing strength scaling alone: +1.7 Sharpe.

---

## Tweet 4 (Complexity Chart) — attach `8_complexity_vs_performance.png`

This is the chart that blew our minds.

Complexity went DOWN while performance went UP.

The AI independently discovered what veteran quants know: most alpha comes from a few robust signals. Everything else is noise dressed up as sophistication.

Uniform sizing > sophisticated sizing. Simple momentum > multi-timeframe confirmation.

---

## Tweet 5 (The Killer Finding) — attach `6_top_discoveries.png`

The single biggest gain: changing RSI period from 14 to 8.

+5 Sharpe points from one parameter.

Why? RSI(14) was designed for daily bars in the 1970s. Hourly crypto moves faster. The AI figured this out through pure trial and error — no finance textbooks, no human intuition.

---

## Tweet 6 (Drawdown) — attach `4_drawdown_evolution.png`

Max drawdown evolution is equally wild.

Started at 7.6%. Ended at 0.3%.

That's a 96% reduction in worst-case loss. The strategy went from "scary to trade" to "barely moves against you."

The key: ATR trailing stops at 5.5x + RSI mean-reversion exits at 69/31. Let winners run, cut losers with surgical precision.

---

## Tweet 7 (Final Architecture) — attach `7_strategy_architecture.png`

The final strategy the AI converged on is remarkably elegant:

6 signals vote → need 4/6 agreement
→ ATR trailing stop (5.5x)
→ RSI mean-reversion exit
→ Signal flip (never exit flat)

Equal weight BTC/ETH/SOL. 8% position size. 2-bar cooldown.

Every "smart" feature was tried, kept temporarily, then permanently removed.

---

## Tweet 8 (Stats) — attach `5_keep_discard.png`

By the numbers:

- 251 total experiments (104 in main results log)
- 44 kept, 59 discarded (43% success rate)
- 7 distinct phases of evolution
- 9 features built then removed
- Score improved 7.9x from baseline
- Entire run: zero human intervention

---

## Tweet 9 (What This Means)

What's happening in autoresearch right now:
- @kaboratsky — optimizing LLM training
- @hamostaf04 — evolving agent protocols
- Gastown — 20-30 Claude Codes in parallel

We're evolving domain knowledge. The AI isn't learning how to code better — it's learning how to be a better quant researcher through pure experimentation.

---

## Tweet 10 (CTA)

Full evolution log with math for every single experiment is open source.

251 experiments. Every keep, every discard, every lesson — all generated autonomously.

github.com/Nunchi-trade/auto-researchtrading

We're @nunaboratrade. Building autonomous DeFi infrastructure on Hyperliquid.

---

## Suggested Image Pairing Summary

| Tweet | Chart File |
|-------|-----------|
| 1 (Hook) | `1_score_evolution.png` |
| 2 (Setup) | `2_before_after.png` |
| 3 (Simplification) | `3_simplification.png` |
| 4 (Complexity) | `8_complexity_vs_performance.png` |
| 5 (RSI Discovery) | `6_top_discoveries.png` |
| 6 (Drawdown) | `4_drawdown_evolution.png` |
| 7 (Architecture) | `7_strategy_architecture.png` |
| 8 (Stats) | `5_keep_discard.png` |
| 9 (Ecosystem) | No image (text only) |
| 10 (CTA) | Repo screenshot or logo |
