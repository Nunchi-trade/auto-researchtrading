# Autoresearch Loop

## Original Autonomous Loop

The original project pattern is:

1. Read current strategy and recent scores
2. Modify `strategy.py`
3. Run `uv run backtest.py`
4. Keep the change if score improves
5. Revert if score does not improve
6. Repeat indefinitely

The historical Claude Code entrypoint was `/autoresearch`.

## Scoring

```text
score = sharpe × √(min(trades/50, 1.0)) − drawdown_penalty − turnover_penalty
drawdown_penalty = max(0, max_drawdown_pct − 15) × 0.05
turnover_penalty = max(0, annual_turnover/capital − 500) × 0.001
```

Hard cutoffs:

- fewer than 10 trades
- drawdown above 50%
- more than 50% capital loss

## Experiment Recording

- one commit per experiment
- `results.tsv` is the lightweight experiment log
- keep changes only when objective metrics improve

## Current Direction

The original loop was built for Hyperliquid `strategy.py`.
Current follow-on work is focused on Upbit spot and Upbit MTF research automation.
