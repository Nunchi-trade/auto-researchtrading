# CLAUDE.md

This repository started as a Karpathy-style autonomous research loop for Hyperliquid trading strategies and now also contains Upbit spot and Upbit multi-timeframe research code.

## Working Model

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
- Hyperliquid autoresearch assumptions still center on `strategy.py`, but current strategy improvement work may target the Upbit files instead

## Practical Context

- The historical Hyperliquid baseline to beat is `2.724`
- The historical best recorded Hyperliquid result is `20.634`
- The strongest historical lesson was that simplifying strategies often improved performance more than adding complexity
- Current follow-on research is focused on automation and improvement of the Upbit MTF strategy under explicit return and drawdown constraints

## Read Next

Start with `docs/README.md`, then load only the relevant document set for the task.

Core indexed docs:

- `docs/context/repo-overview.md`
- `docs/context/autoresearch-loop.md`
- `docs/context/current-baselines.md`

Background references:

- `README.md`
- `STRATEGIES.md`
- `program.md`
