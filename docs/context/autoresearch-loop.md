# Autoresearch Loop

## Project-Level Autoresearch

The repository now uses `autoresearch` as a project-level skill rather than a Hyperliquid-only shortcut.

The first step is always:

1. Read `AGENTS.md`
2. Read `CLAUDE.md`
3. Read `docs/README.md`
4. Choose the active research track

Track routing:

- Hyperliquid original loop: edit `strategy.py`, run `uv run backtest.py`
- Upbit spot loop: edit `upbit_strategy.py`, run `uv run upbit_backtest.py`
- Upbit MTF loop: edit `upbit_mtf_strategy.py` or `upbit_mtf_research.py`, run `uv run scripts/upbit_mtf_search.py`

Claude Code and Codex are expected to follow the same routing model.

## Original Hyperliquid Loop

The original project pattern was:

1. Read current strategy and recent scores
2. Modify `strategy.py`
3. Run `uv run backtest.py`
4. Keep the change if score improves
5. Revert if score does not improve
6. Repeat indefinitely

The historical Claude Code entrypoint was `/autoresearch`, but the loop itself was Hyperliquid-specific.

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
- use a dedicated experiment branch before relying on `git reset --hard HEAD~1`

## Current Direction

- The original loop was built for Hyperliquid `strategy.py`
- Current follow-on work is focused on Upbit spot and Upbit MTF research automation
- Upbit MTF should be judged by its own research objective, not by the old Hyperliquid score
