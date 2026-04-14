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

- `FULL_LONG_PCT=0.92`
- `REDUCED_PCT=0.576`
- `REDUCED_HIGH_PCT=0.576`
- `REDUCED_LOW_PCT=0.00`
- `MACRO_FULL_THRESHOLD=0.58`
- `MACRO_REDUCED_THRESHOLD=0.55`
- `MICRO_FULL_THRESHOLD=0.50`
- `MICRO_ENTER_FULL_THRESHOLD=0.52`
- `MICRO_EXIT_FULL_THRESHOLD=0.46`
- `MICRO_REDUCED_THRESHOLD=0.40`
- `MAX_MACRO_DRAWDOWN=0.07`
- `STATE_CONFIRM_BARS=4`
- `MIN_STATE_HOLD_BARS=1`
- `MIN_REBALANCE_FRACTION=0.12`

Observed targeted-search result:

- objective: `54602.62`
- full-period excess return: `54601.17%`
- full-period max drawdown: `14.72%`
- test-period excess return: `74.90%`

Current default-parameter evaluation snapshot:

- params: `FULL_LONG_PCT=0.92`, `REDUCED_PCT=0.576`, `REDUCED_HIGH_PCT=0.576`, `REDUCED_LOW_PCT=0.00`, `MACRO_FULL_THRESHOLD=0.58`, `MACRO_REDUCED_THRESHOLD=0.55`, `MICRO_FULL_THRESHOLD=0.50`, `MICRO_ENTER_FULL_THRESHOLD=0.52`, `MICRO_EXIT_FULL_THRESHOLD=0.46`, `MICRO_REDUCED_THRESHOLD=0.40`, `MAX_MACRO_DRAWDOWN=0.07`, `STATE_CONFIRM_BARS=4`, `MIN_STATE_HOLD_BARS=1`, `MIN_REBALANCE_FRACTION=0.12`
- objective: `54602.62`
- full-period excess return: `54601.17%`
- full-period max drawdown: `14.72%`
- full-period trades: `1238`
- test-period excess return: `74.90%`
- test-period max drawdown: `7.09%`

Walk-forward validation snapshot for the current candidate:

- 180d test windows, 2y train / 180d step: mean excess `-6.27%`, min excess `-210.26%`, max test DD `9.39%`, positive ratio `61.54%`
- 1y test windows, 2y train / 1y step: mean excess `4.56%`, min excess `-71.22%`, max test DD `9.39%`, positive ratio `66.67%`

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
