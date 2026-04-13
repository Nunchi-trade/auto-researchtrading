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

Current DD<15 autoresearch candidate under dynamic slippage and taker-fee costs:

- `FULL_LONG_PCT=0.90`
- `REDUCED_PCT=0.549`
- `REDUCED_HIGH_PCT=0.549`
- `REDUCED_LOW_PCT=0.30`
- `MACRO_FULL_THRESHOLD=0.62`
- `MACRO_REDUCED_THRESHOLD=0.45`
- `MICRO_FULL_THRESHOLD=0.50`
- `MICRO_ENTER_FULL_THRESHOLD=0.54`
- `MICRO_EXIT_FULL_THRESHOLD=0.46`
- `MICRO_REDUCED_THRESHOLD=0.40`
- `MAX_MACRO_DRAWDOWN=0.10`
- `STATE_CONFIRM_BARS=2`
- `MIN_STATE_HOLD_BARS=1`

Observed targeted-search result:

- objective: `26844.28`
- full-period excess return: `26893.56%`
- full-period max drawdown: `14.99%`
- test-period excess return: `53.26%`

Current default-parameter evaluation snapshot:

- params: `FULL_LONG_PCT=0.90`, `REDUCED_PCT=0.549`, `REDUCED_HIGH_PCT=0.549`, `REDUCED_LOW_PCT=0.30`, `MACRO_FULL_THRESHOLD=0.62`, `MACRO_REDUCED_THRESHOLD=0.45`, `MICRO_FULL_THRESHOLD=0.50`, `MICRO_ENTER_FULL_THRESHOLD=0.54`, `MICRO_EXIT_FULL_THRESHOLD=0.46`, `MICRO_REDUCED_THRESHOLD=0.40`, `MAX_MACRO_DRAWDOWN=0.10`, `STATE_CONFIRM_BARS=2`, `MIN_STATE_HOLD_BARS=1`
- objective: `26844.28`
- full-period return: `29186.49%`
- full-period buy-and-hold: `2292.9%`
- full-period excess return: `26893.56%`
- full-period max drawdown: `14.99%`
- full-period trades: `3396`
- test-period return: `67.10%`
- test-period buy-and-hold: `13.84%`
- test-period excess return: `53.26%`
- test-period max drawdown: `5.98%`

Walk-forward validation snapshot for the current candidate:

- 180d test windows, 2y train / 180d step: mean excess `-12.84%`, min excess `-242.53%`, max test DD `9.12%`, positive ratio `61.54%`
- 1y test windows, 2y train / 1y step: mean excess `-11.33%`, min excess `-108.16%`, max test DD `9.12%`, positive ratio `50.00%`

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
