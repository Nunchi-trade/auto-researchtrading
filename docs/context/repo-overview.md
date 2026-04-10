# Repo Overview

## Commands

```bash
uv run prepare.py
uv run backtest.py
uv run run_benchmarks.py
uv run backtest.py > run.log 2>&1
grep "^score:\|^sharpe:\|^max_drawdown_pct:" run.log
```

## Fixed Hyperliquid Harness

- `prepare.py` — data download, backtest engine, and shared datatypes
- `backtest.py` — runs the current `strategy.py`
- `benchmarks/` — reference strategies

## Main Mutable Surfaces

- `strategy.py` — original Hyperliquid single-file strategy loop
- `upbit_prepare.py` — Upbit spot data and backtest harness
- `upbit_strategy.py` — Upbit spot strategy
- `upbit_mtf_strategy.py` — Upbit multi-timeframe strategy
- `upbit_mtf_research.py` — Upbit MTF parameter search and evaluation

## Constraints

- Allowed packages: `numpy`, `pandas`, `scipy`, `requests`, `pyarrow`, stdlib
- Historical Hyperliquid loop assumes `strategy.py` is the only mutable file
- Newer Upbit research work is not bound to that single-file rule
