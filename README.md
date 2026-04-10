<p align="center">
  <img src="assets/logo.png" alt="Nunchi" width="480" />
</p>

<h3 align="center">Autonomous Trading Strategy Research</h3>

<p align="center">
  Karpathy-style autoresearch for Hyperliquid perpetual futures — 103 experiments, zero human intervention
</p>

<p align="center">
  <a href="https://github.com/Nunchi-trade/agent-cli"><strong>Agent CLI</strong></a> &nbsp;•&nbsp;
  <a href="https://docs.nunchi.trade"><strong>Docs</strong></a> &nbsp;•&nbsp;
  <a href="https://research.nunchi.trade"><strong>Research</strong></a> &nbsp;•&nbsp;
  <a href="https://discord.gg/nunchi"><strong>Discord</strong></a> &nbsp;•&nbsp;
  <a href="https://x.com/nunchi"><strong>X</strong></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/experiments-103-C9A84C" alt="Experiments" />
  <img src="https://img.shields.io/badge/max%20drawdown-0.3%25-brightgreen" alt="Drawdown" />
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License" />
</p>

---

An AI agent autonomously modifies a trading strategy, backtests each change, and keeps only improvements. The original system was built around a single-file Hyperliquid loop (`strategy.py`), and this repository now also contains Upbit spot and Upbit multi-timeframe research flows. It adapts [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) pattern for trading strategy discovery. Starting from a simple momentum baseline (Sharpe 2.7), the original Hyperliquid loop discovered a 6-signal ensemble strategy achieving **Sharpe 21.4 with 0.3% max drawdown** — a 7.9x improvement over 103 fully autonomous experiments.

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Setup

```bash
git clone https://github.com/Nunchi-trade/auto-researchtrading.git
cd auto-researchtrading
uv run prepare.py                # Download data (~1 min, cached to ~/.cache/autotrader/data/)
```

No API keys required. Data is fetched from public CryptoCompare and Hyperliquid APIs.

### Run a Backtest

```bash
uv run backtest.py               # Run current strategy against validation data
```

```
score:              20.634000
sharpe:             20.634000
total_return_pct:   130.000000
max_drawdown_pct:   0.300000
num_trades:         7605
```

### Project Tracks

This repository now has three distinct research surfaces:

- Hyperliquid original loop: `prepare.py`, `backtest.py`, `strategy.py`
- Upbit spot: `upbit_prepare.py`, `upbit_backtest.py`, `upbit_strategy.py`
- Upbit MTF research: `upbit_mtf_strategy.py`, `upbit_mtf_research.py`, `scripts/upbit_mtf_search.py`

Use the Hyperliquid path when you want the original single-file autoresearch loop. Use the Upbit paths when working on spot or multi-timeframe strategy research.

### Run All Benchmarks

```bash
uv run run_benchmarks.py         # Compare 5 reference strategies
```

---

## Running Your Own Experiments

### Rules

| Rule | Detail |
|------|--------|
| **Only edit `strategy.py`** | This is the single mutable file |
| **Do not modify** | `prepare.py`, `backtest.py`, or anything in `benchmarks/` |
| **No new dependencies** | Only `numpy`, `pandas`, `scipy`, `requests`, `pyarrow`, and stdlib |
| **Time budget** | 120 seconds per backtest |

### Manual Experiment Loop

```bash
git checkout -b autotrader/myexp          # 1. Create experiment branch

# 2. Edit strategy.py with your idea (parameters, signals, entry/exit logic)

uv run backtest.py                        # 3. Run the backtest

# 4. If score improved → keep
git add strategy.py && git commit -m "exp1: description of change"

# 5. If score got worse → revert
git reset --hard HEAD~1
```

Repeat. Each commit is one atomic experiment. The git history becomes your experiment log.

### Autonomous Loop (Claude Code or Codex)

The repository-level `autoresearch` skill can be used from either [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or Codex. The skill now routes to the active project track instead of assuming every task is the original `strategy.py` loop.

```bash
claude                           # Start Claude Code from repo root
/autoresearch                    # Launch the autonomous loop
```

Codex should use the same `autoresearch` skill from repo root after loading `AGENTS.md` and `CLAUDE.md`.

The agent will:
1. Read the indexed project context from `AGENTS.md`, `CLAUDE.md`, and `docs/README.md`
2. Choose the active research track: Hyperliquid, Upbit spot, or Upbit MTF
3. Run the matching backtest or search harness
4. Keep the change if the active track's objective improves, revert if not
5. Repeat until interrupted

Recommended command for the current Upbit MTF autoresearch track:

```bash
uv run python -u scripts/upbit_mtf_search.py \
  --grid coarse \
  --top 10 \
  --progress-every 1 \
  --max-evals 1 \
  --results-path ~/.cache/autotrader_upbit/mtf-autoresearch.jsonl
```

For the original Hyperliquid-only loop, see [`program.md`](program.md). For the current indexed project context, start with [`CLAUDE.md`](CLAUDE.md).

---

## Strategy Interface

Your strategy must implement a `Strategy` class with a single `on_bar()` method — no shared state, no hidden coupling.

```python
class Strategy:
    def __init__(self):
        # Initialize any tracking state
        pass

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list[Signal]:
        """
        Called once per hourly bar across all symbols.

        Args:
            bar_data: dict of symbol → BarData
                - BarData.close, .open, .high, .low, .volume, .funding_rate
                - BarData.history: DataFrame of last 500 bars
            portfolio: PortfolioState
                - portfolio.cash: available cash
                - portfolio.positions: dict of symbol → signed USD notional

        Returns:
            List of Signal(symbol, target_position, order_type="market")
            target_position is signed USD notional (+long, -short, 0=close)
        """
        return []
```

### Data Available

| Field | Description |
|-------|-------------|
| `bar_data[symbol].history` | DataFrame of last 500 hourly bars |
| Columns | `timestamp`, `open`, `high`, `low`, `close`, `volume`, `funding_rate` |
| Symbols | BTC, ETH, SOL |
| Validation period | 2024-07-01 to 2025-03-31 |
| Initial capital | $100,000 |
| Fees | 2 bps maker, 5 bps taker, 1 bps slippage |

### Scoring Formula

```
score = sharpe × √(min(trades/50, 1.0)) − drawdown_penalty − turnover_penalty
```

| Component | Formula |
|-----------|---------|
| Sharpe | `mean(daily_returns) / std(daily_returns) × √365` |
| Drawdown penalty | `max(0, max_drawdown_pct − 15) × 0.05` |
| Turnover penalty | `max(0, annual_turnover/capital − 500) × 0.001` |
| Hard cutoffs (→ −999) | Fewer than 10 trades, drawdown > 50%, lost > 50% of capital |

---

## Benchmarks

5 reference strategies to beat. The baseline to clear is **2.724**.

| Rank | Strategy | Score | Sharpe | Return | Max DD | Trades |
|------|----------|-------|--------|--------|--------|--------|
| 1 | `simple_momentum` | 2.724 | 2.724 | +42.6% | 7.6% | 9081 |
| 2 | `funding_arb` | -0.191 | -0.191 | -1.3% | 9.4% | 1403 |
| 3 | `regime_mm` | -0.322 | -0.322 | -3.1% | 11.2% | 12854 |
| 4 | `mean_reversion` | -3.964 | -3.380 | -26.2% | 26.7% | 3185 |
| 5 | `momentum_breakout` | -999 | — | — | — | 0 |

---

## Results

### Score Progression (103 Autonomous Experiments)

| Experiment | Score | Sharpe | Max DD | Trades | Key Change |
|-----------|-------|--------|--------|--------|------------|
| Baseline | 2.724 | 2.724 | 7.6% | 9081 | Simple momentum starting point |
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

**Final score: 20.634** — 7.6x improvement over baseline, fully autonomous.

### Key Discoveries

| Rank | Discovery | Impact | Insight |
|------|-----------|--------|---------|
| 1 | **RSI period 8** | +5.0 Sharpe | Standard 14-period RSI is too slow for hourly crypto |
| 2 | **Remove strength scaling** | +1.7 Sharpe | Uniform sizing beats momentum-weighted sizing |
| 3 | **Simplified momentum** | +0.8 Sharpe | Just `ret > threshold`, no multi-timeframe confirmation needed |
| 4 | **BB width compression** | +0.9 Sharpe | Bollinger Band width percentile as 6th ensemble signal |
| 5 | **ATR 5.5 trailing stop** | +1.0 Sharpe | Hold winners much longer than conventional 3.5x ATR |
| 6 | **The Great Simplification** | +2.0 Sharpe | Removing pyramiding, funding boost, BTC filter, correlation filter |
| 7 | **Position size 0.08** | +0.6 Sharpe | Smaller positions eliminate turnover penalty |

### Biggest Lesson: Simplicity Wins

The strongest gains came from *removing* complexity, not adding it. Every "smart" feature — BTC lead-lag filter, correlation-based weight adjustment, momentum strength scaling, pyramiding, funding carry — was tested, then permanently removed when it hurt performance. The final strategy is remarkably simple.

See [`STRATEGIES.md`](STRATEGIES.md) for the complete evolution log with mathematical details for all 103 experiments.

---

## Best Strategy Architecture

**6-signal ensemble with 4/6 majority vote:**

| Signal | Bull Condition | Bear Condition |
|--------|---------------|----------------|
| Momentum | 12h return > dynamic threshold | 12h return < -dynamic threshold |
| Very-short momentum | 6h return > threshold × 0.7 | 6h return < -threshold × 0.7 |
| EMA crossover | EMA(7) > EMA(26) | EMA(7) < EMA(26) |
| RSI(8) | RSI > 50 | RSI < 50 |
| MACD(14,23,9) | MACD histogram > 0 | MACD histogram < 0 |
| BB compression | BB width < 85th percentile | BB width < 85th percentile |

**Exit conditions (priority order):**
1. **ATR trailing stop** — 5.5x ATR from peak/trough
2. **RSI mean-reversion** — Exit longs at RSI > 69, exit shorts at RSI < 31
3. **Signal flip** — Reverse position when opposing ensemble fires

**Key parameters:**

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `BASE_POSITION_PCT` | 0.08 | Per-symbol position size as fraction of equity |
| `COOLDOWN_BARS` | 2 | Minimum bars between exit and re-entry |
| `RSI_PERIOD` | 8 | Fast RSI tuned for hourly crypto |
| `ATR_STOP_MULT` | 5.5 | Wide trailing stop to let winners run |
| `MIN_VOTES` | 4 | Majority vote threshold (4 of 6 signals) |

---

## Project Structure

```
├── strategy.py          # The only file you edit — your strategy lives here
├── backtest.py          # Entry point — runs one backtest (fixed, do not modify)
├── prepare.py           # Data download + backtest engine (fixed, do not modify)
├── run_benchmarks.py    # Run all 5 benchmark strategies
├── benchmarks/          # 5 reference strategies for comparison
│   ├── simple_momentum.py
│   ├── funding_arb.py
│   ├── regime_mm.py
│   ├── mean_reversion.py
│   └── momentum_breakout.py
├── program.md           # Detailed instructions for the autonomous loop
├── STRATEGIES.md        # Complete evolution log of all 103 experiments
├── charts/              # Visualization PNGs of experiment progression
├── pyproject.toml       # Dependencies (numpy, pandas, scipy, requests, pyarrow)
└── uv.lock              # Locked dependencies for reproducibility
```

---

## Branches

| Branch | Description |
|--------|-------------|
| `main` | Base scaffold and data pipeline |
| `autotrader/mar10c` | Best autotrader strategy (score 20.634) |
| `autoresearch/mar10-opus` | LLM training optimization experiments |

---

## Attribution

Built on [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) pattern. Data from [CryptoCompare](https://www.cryptocompare.com/) and [Hyperliquid](https://hyperliquid.xyz).

---

## Links

- **Agent CLI** — [github.com/Nunchi-trade/agent-cli](https://github.com/Nunchi-trade/agent-cli)
- **Docs** — [docs.nunchi.trade](https://docs.nunchi.trade)
- **Research** — [research.nunchi.trade](https://research.nunchi.trade)
- **Discord** — [discord.gg/nunchi](https://discord.gg/nunchi)
- **X** — [@nunchi](https://x.com/nunchi)

---

<p align="center">
  <sub>Built by <a href="https://nunchi.trade">Nunchi</a> • MIT License</sub>
</p>
