# Current Baselines

## Hyperliquid Reference Point

- baseline to beat: `2.724` from `simple_momentum`
- historical best: `20.634` from `exp102`

## Best Known Hyperliquid Pattern

The strongest historical result used a 6-signal ensemble:

- momentum (12h)
- very-short momentum (6h)
- EMA crossover
- RSI(8)
- MACD
- Bollinger Band width compression

Entry required 4 of 6 votes.
Exit priority was ATR trailing stop, then RSI overbought/oversold, then signal flip.

Key parameters:

- `BASE_POSITION_PCT=0.08`
- `COOLDOWN_BARS=2`
- `RSI_PERIOD=8`
- `ATR_STOP_MULT=5.5`
- `MIN_VOTES=4`

## Upbit MTF Reference Candidate

Current DD<15 autoresearch candidate:

- `FULL_LONG_PCT=0.90`
- `REDUCED_PCT=0.55`
- `MACRO_FULL_THRESHOLD=0.62`
- `MICRO_FULL_THRESHOLD=0.50`
- `MAX_MACRO_DRAWDOWN=0.10`

Observed targeted-search result:

- objective: `15902.32`
- full-period excess return: `16008.3%`
- full-period max drawdown: `14.6%`
- test-period excess return: `39.4%`

Current default-parameter evaluation snapshot:

- params: `FULL_LONG_PCT=0.90`, `REDUCED_PCT=0.55`, `MACRO_FULL_THRESHOLD=0.62`, `MICRO_FULL_THRESHOLD=0.50`, `MAX_MACRO_DRAWDOWN=0.10`
- objective: `15902.32`
- full-period return: `18301.2%`
- full-period buy-and-hold: `2292.9%`
- full-period excess return: `16008.3%`
- full-period max drawdown: `14.63%`
- full-period trades: `5987`
- test-period return: `53.22%`
- test-period buy-and-hold: `13.84%`
- test-period excess return: `39.38%`
- test-period max drawdown: `7.55%`

## Upbit Spot Snapshot

Current `uv run upbit_backtest.py` snapshot on `val` split with `60`-minute candles:

- score: `2.336701`
- sharpe: `2.336701`
- total return: `27.15%`
- max drawdown: `3.44%`
- trades: `184`
- win rate: `34.78%`
- profit factor: `2.66`

## Biggest Historical Lesson

Removing complexity improved results more than adding it.
The following ideas were tried and removed:

- pyramiding
- funding boost
- BTC filter
- correlation filter
- strength scaling
