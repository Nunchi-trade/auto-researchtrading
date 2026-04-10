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

## Biggest Historical Lesson

Removing complexity improved results more than adding it.
The following ideas were tried and removed:

- pyramiding
- funding boost
- BTC filter
- correlation filter
- strength scaling
