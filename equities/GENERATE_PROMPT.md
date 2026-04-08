You are a quantitative trading strategy developer. Generate a complete Python strategy file.

## Strategy Interface

The strategy must implement this exact interface:

```python
from prepare import Signal, PortfolioState, BarData

class Strategy:
    def __init__(self, symbols=None):
        # symbols: list of ticker strings like ["SPY", "QQQ"]
        # Store any state needed across bars here
        ...

    def on_bar(self, bar_data: dict, portfolio: PortfolioState) -> list:
        # Called once per daily bar
        #
        # bar_data: dict mapping symbol string -> BarData
        #   bar_data[symbol].close   (float, current bar close)
        #   bar_data[symbol].open    (float)
        #   bar_data[symbol].high    (float)
        #   bar_data[symbol].low     (float)
        #   bar_data[symbol].volume  (float)
        #   bar_data[symbol].history (pandas DataFrame, last 250 bars)
        #     columns: timestamp, open, high, low, close, volume
        #
        # portfolio:
        #   portfolio.equity    (float, total portfolio value)
        #   portfolio.cash      (float, available cash)
        #   portfolio.positions (dict: symbol -> signed USD notional)
        #     positive = long, negative = short, absent = no position
        #
        # Return: list of Signal objects
        #   Signal(symbol=str, target_position=float)
        #   target_position is signed USD notional:
        #     positive = go long that amount
        #     negative = go short that amount
        #     0.0 = close the position
        #   Only emit a signal when you want to CHANGE a position.
        #   Minimum position change threshold is $1.0.
        ...
```

## Available Libraries

You may ONLY import from these:
- `numpy` (as np)
- `pandas` (as pd)
- `scipy` (scipy.stats, scipy.signal, scipy.optimize, scipy.linalg)
- `scikit-learn` (sklearn.ensemble, sklearn.linear_model, sklearn.preprocessing, etc.)
- `prepare` (Signal, PortfolioState, BarData)
- Python standard library (math, collections, itertools, functools, dataclasses)

Do NOT import anything else. No requests, no yfinance, no ta-lib, no external packages.

## Data Constraints

- **Daily bars** (not intraday)
- **250-bar history** window (~1 trading year)
- **OHLCV** data per symbol (no order book, no fundamentals, no news)
- **Val period**: 2023-01-01 to 2024-12-31 (~504 trading days)
- **252 trading days per year**
- **Initial capital**: $100,000
- **Max leverage**: 2x (total exposure cannot exceed 2x equity)
- **Commission-free**, 1 bps slippage per trade

## Scoring Formula

```
score = sharpe * sqrt(min(trades / 50, 1.0)) - drawdown_penalty - turnover_penalty

drawdown_penalty = max(0, max_drawdown_pct - 15) * 0.05
turnover_penalty = max(0, annual_turnover / capital - 500) * 0.001

Hard cutoffs (score = -999):
  - Less than 10 trades
  - Max drawdown > 50%
  - Lost more than 50% of capital
```

Higher score is better. The score is dominated by Sharpe ratio. You MUST generate at least 10 trades to avoid the -999 cutoff.

## Important Implementation Notes

1. Check `if symbol not in bar_data: continue` — not all symbols have data on every bar
2. Check `len(bd.history) < N` before accessing history — early bars have insufficient data
3. Use `portfolio.positions.get(symbol, 0.0)` for safe position lookup
4. Position sizes should be reasonable fractions of equity (e.g., 5-15% per symbol)
5. Always have exit conditions — strategies that only enter but never exit will blow up
6. The backtest has a 120-second time budget — avoid O(n²) or worse complexity per bar

## Output Format

Output ONLY the complete Python file content inside a single ```python code block.
Do not include any explanation before or after the code block.

{reference_section}

## Strategy to Implement

{description}
