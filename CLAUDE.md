# CLAUDE.md

This repository started as a Karpathy-style autonomous research loop for Hyperliquid trading strategies and now also contains Upbit spot and Upbit multi-timeframe research code.

## Working Model

- The repository-level `autoresearch` skill now routes by track after reading this file and `docs/README.md`
- Original autonomous loop: repeatedly modify `strategy.py`, run `uv run backtest.py`, keep improvements, revert regressions
- Newer work in this repo extends beyond the original single-file loop and includes:
  - Upbit spot data + backtest harness
  - Upbit spot strategy research
  - Upbit multi-timeframe strategy and parameter search
  - TradingAgents-based crypto research scaffolding

## Main Entry Points

- Hyperliquid baseline loop:
  - `prepare.py`
  - `backtest.py`
  - `strategy.py`
- Upbit spot:
  - `upbit_prepare.py`
  - `upbit_backtest.py`
  - `upbit_strategy.py`
- Upbit MTF research:
  - `upbit_mtf_strategy.py`
  - `upbit_mtf_research.py`
  - `scripts/upbit_mtf_search.py`

## Important Constraints

- Prefer existing libraries only: `numpy`, `pandas`, `scipy`, `requests`, `pyarrow`, stdlib
- Do not treat the original Hyperliquid harness and the newer Upbit research flow as the same system
- `autoresearch` is project-wide, but each track keeps its own harness, metrics, and entry points
- Hyperliquid autoresearch assumptions still center on `strategy.py`, but current strategy improvement work may target the Upbit files instead

## Practical Context

- The historical Hyperliquid baseline to beat is `2.724`
- The historical best recorded Hyperliquid result is `20.634`
- The strongest historical lesson was that simplifying strategies often improved performance more than adding complexity
- Current follow-on research is focused on automation and improvement of the Upbit MTF strategy under explicit return and drawdown constraints
- Claude and Codex should both use the same project-level `autoresearch` skill semantics

## Read Next

Start with `docs/README.md`, then load only the relevant document set for the task.

If the user asks for autonomous research, first decide which track is active:

- Hyperliquid loop: `strategy.py`
- Upbit spot loop: `upbit_strategy.py`
- Upbit MTF loop: `upbit_mtf_strategy.py` plus `upbit_mtf_research.py`

Recommended Upbit MTF autoresearch command:

`uv run python -u scripts/upbit_mtf_search.py --grid coarse --top 10 --progress-every 1 --max-evals 1 --results-path ~/.cache/autotrader_upbit/mtf-autoresearch.jsonl`

Core indexed docs:

- `docs/context/repo-overview.md`
- `docs/context/autoresearch-loop.md`
- `docs/context/current-baselines.md`

Background references:

- `README.md`
- `STRATEGIES.md`
- `program.md`
