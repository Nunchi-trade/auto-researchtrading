# Council Mode — adversarial convergence verification

You are running a **Council Mode session**. The normal experiment loop has detected convergence (N consecutive experiments with no improvement). Your job is to generate diverse adversarial proposals to either break through the plateau or confirm the strategy is near-optimal.

## Your task

1. **Read context**: Read `strategy.py`, `results.tsv`, and run `git log main..HEAD --oneline`.
2. **Analyze**: Identify the current best score, recent experiment history, and what has been tried.
3. **Generate 3-5 proposals**, each from a **distinct philosophy**:
   - **Simplification** — remove a component; test if performance holds without it
   - **Contrarian** — opposite of current approach (e.g., momentum → mean-reversion)
   - **Regime-shift** — what if market conditions shifted? (different vol regime, correlation breakdown)
   - **Scale-change** — different timeframe, asset weighting, or position sizing approach
   - **Radical** — completely different approach to the problem
4. **Anonymize & rank**: Label as Proposal A/B/C/D/E. Evaluate each on: pros, cons, overfitting risk, regime robustness, complexity cost. Output `FINAL RANKING: 1. Proposal X, 2. Proposal Y...`
5. **Execute in ranked order**: Apply #1, commit, backtest. If it improves score → keep and stop. If not → revert, try #2, then #3, etc.
6. **Output final verdict** (CRITICAL — the outer shell parses this):

If **any proposal improved** the score:
```
echo "COUNCIL_VERDICT: ACCEPT"
```

If **all proposals failed** to improve:
```
echo "COUNCIL_VERDICT: PASS"
```

You MUST output exactly one of these two lines as the very last thing before exiting.

## What you CAN do

- Modify `strategy.py` — this is the only file you edit.
- Run `uv run backtest.py > run.log 2>&1` for each proposal.
- Commit and revert as needed.

## What you CANNOT do

- Modify `prepare.py`, `backtest.py`, or anything in `benchmarks/`.
- Install new packages. Only numpy, pandas, scipy, and standard library.
- Look at test set data.
- Skip proposals — you must test at least 3 before declaring PASS.

## Council log

Append your session results to `council_log.md`:

```markdown
## Council Session #N — (score: <best_score>)

**Date:** <today>
**Trigger:** <N> consecutive no-improvement experiments
**Baseline:** score=<X>, sharpe=<Y>, dd=<Z>

### Proposals

| Label | Philosophy | Description |
|-------|-----------|-------------|
| A | ... | ... |
| B | ... | ... |
| C | ... | ... |

### Ranking

FINAL RANKING: 1. A, 2. C, 3. B — rationale: ...

### Results

| Proposal | Score | vs Baseline | Outcome |
|----------|-------|-------------|---------|
| A | ... | ... | discard/keep |
| C | ... | ... | discard/keep |
| B | ... | ... | discard/keep |

### Verdict

COUNCIL_PASS / COUNCIL_ACCEPT Proposal X (philosophy)
```

## Results TSV

Also record each proposal test in `results.tsv`:
```
commit	score	sharpe	max_dd	status	description
```

Use status `council_discard` or `council_keep` to distinguish from normal experiments.

## Scoring formula (from prepare.py)

```
score = sharpe * sqrt(trade_count_factor) - drawdown_penalty - turnover_penalty
trade_count_factor = min(num_trades / 50, 1.0)
drawdown_penalty = max(0, max_drawdown_pct - 15) * 0.05
turnover_penalty = max(0, annual_turnover/capital - 500) * 0.001
Hard cutoffs: <10 trades → -999, >50% drawdown → -999, lost >50% → -999
```
