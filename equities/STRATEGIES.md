# Equities Strategy Evolution Log

## Scoring Formula

```
score = sharpe × √(min(trades/50, 1.0)) − drawdown_penalty − turnover_penalty
drawdown_penalty = max(0, max_dd% − 15) × 0.05
turnover_penalty = max(0, annual_turnover/capital − 500) × 0.001
Hard cutoffs: <10 trades → −999, >50% DD → −999, lost >50% → −999
```

## Mathematical Primitives

- **EMA(x, span)**: α = 2/(span+1), EMA_t = α·x_t + (1−α)·EMA_{t−1}
- **RSI(closes, period)**: RS = avg_gain/avg_loss, RSI = 100 − 100/(1+RS)
- **ATR(H, L, C, n)**: mean of max(H−L, |H−C_{t−1}|, |L−C_{t−1}|) over n bars
- **MACD(closes, fast, slow, signal)**: MACD = EMA(fast) − EMA(slow), histogram = MACD − EMA(MACD, signal)
- **BB width percentile**: (2σ/SMA) ranked against its own history
- **Realized vol**: std(log returns) over lookback window
- **Dynamic threshold**: BASE_THRESHOLD × (0.3 + vol_ratio × 0.7), clamped [0.005, 0.030]

## Phase 1: Initial Adaptation (from crypto)

### exp0: Baseline — crypto ensemble ported to daily equities

5-signal ensemble (momentum, EMA crossover, RSI, MACD, BB compression).
3/5 majority vote. ATR 2.5× trailing stop. Daily bars.

Parameters: EMA 10/30, RSI 14, MACD 12/26/9, BB 20, position 8%, threshold 1%, cooldown 2 bars.

Default symbols: SPY, QQQ, IWM, XLE, XLF, TLT, AAPL, NVDA, JPM, UNH

```
score:              5.582029
sharpe:             5.582029
total_return_pct:   127.007004
max_drawdown_pct:   1.810954
num_trades:         1654
win_rate_pct:       77.323420
profit_factor:      10.396690
```

Strong baseline. 77% win rate, 1.8% max drawdown, 127% return over 2023-2024 val period.
Already 3.9x better than the best benchmark (simple_momentum at 1.447).
