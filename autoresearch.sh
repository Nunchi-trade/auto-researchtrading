#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
TAG="${1:?Usage: ./autoresearch.sh <tag> [max_experiments] [council_threshold]}"
BRANCH="autotrader/${TAG}"
RESULTS="results.tsv"
MAX_EXPERIMENTS="${2:-0}"
COUNCIL_THRESHOLD="${3:-5}"
EXPERIMENT_COUNT=0
COUNCIL_COUNT=0

cd "$PROJECT_DIR"

# Initialize: create branch if it doesn't exist
if ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  git checkout -b "$BRANCH"
  echo -e "commit\tscore\tsharpe\tmax_dd\tstatus\tdescription" > "$RESULTS"
  git add "$RESULTS"
  git commit -m "init: clean slate for ${TAG}"
else
  git checkout "$BRANCH"
fi

echo "Branch: $BRANCH"
echo "Max experiments: ${MAX_EXPERIMENTS:-unlimited}"
echo "Council threshold: $COUNCIL_THRESHOLD consecutive discards"
echo ""

# Count consecutive discards from the tail of results.tsv
count_consecutive_discards() {
  if [ ! -f "$RESULTS" ]; then
    echo 0
    return
  fi
  # Read status column (5th field), count consecutive "discard" from bottom
  tail -n +2 "$RESULTS" | awk -F'\t' '{print $5}' | tac | awk '
    /^discard$/ { count++; next }
    { exit }
    END { print count+0 }
  '
}

# Run a Council Mode session
run_council() {
  local council_num=$((COUNCIL_COUNT + 1))
  echo ""
  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║  COUNCIL MODE #${council_num} — ${COUNCIL_THRESHOLD} consecutive discards detected  ║"
  echo "╚══════════════════════════════════════════════════════════╝"
  echo ""

  local council_output
  council_output=$(CLAUDE_CONFIG_DIR=~/.claude-autoresearch claude -p \
    --dangerously-skip-permissions \
    --model opus \
    --effort max \
    --system-prompt-file "$PROJECT_DIR/program-council.md" \
    --allowedTools "Read,Edit,Write,Bash(git:*),Bash(uv run:*),Bash(grep:*),Bash(tail:*),Bash(head:*),Bash(cat:*),Bash(echo:*),Grep,Glob" \
    "Run Council Mode. Read program-council.md for instructions. This is Council Session #${council_num}." \
    2>&1) || true

  COUNCIL_COUNT=$council_num

  # Parse verdict from output
  if echo "$council_output" | grep -q "COUNCIL_VERDICT: ACCEPT"; then
    echo ""
    echo "Council #${council_num}: ACCEPT — breakthrough found, resuming experiments"
    echo ""
    return 0  # continue looping
  elif echo "$council_output" | grep -q "COUNCIL_VERDICT: PASS"; then
    echo ""
    echo "Council #${council_num}: PASS — strategy confirmed near-optimal"
    echo "Auto-stopping autoresearch."
    echo ""
    return 1  # signal to stop
  else
    echo ""
    echo "Council #${council_num}: no clear verdict detected, treating as PASS"
    echo "Auto-stopping autoresearch."
    echo ""
    return 1  # fail-safe: stop if verdict is unclear
  fi
}

# Main loop
while true; do
  # Check convergence before each experiment
  consecutive_discards=$(count_consecutive_discards)
  if [ "$consecutive_discards" -ge "$COUNCIL_THRESHOLD" ]; then
    if ! run_council; then
      break
    fi
    # Council ACCEPT: reset and continue
  fi

  EXPERIMENT_COUNT=$((EXPERIMENT_COUNT + 1))
  if [ "$MAX_EXPERIMENTS" -gt 0 ] && [ "$EXPERIMENT_COUNT" -gt "$MAX_EXPERIMENTS" ]; then
    echo "Reached max experiments: $MAX_EXPERIMENTS"
    break
  fi

  echo "=== Experiment $EXPERIMENT_COUNT ($(date '+%H:%M:%S')) ==="

  CLAUDE_CONFIG_DIR=~/.claude-autoresearch claude -p \
    --dangerously-skip-permissions \
    --model opus \
    --effort max \
    --system-prompt-file "$PROJECT_DIR/program-stateless.md" \
    --allowedTools "Read,Edit,Write,Bash(git:*),Bash(uv run:*),Bash(grep:*),Bash(tail:*),Bash(head:*),Bash(cat:*),Grep,Glob" \
    "Run one experiment. Read program-stateless.md and results.tsv for context. Run 'git log main..HEAD --oneline' for this branch's experiment history only. Modify strategy.py, commit, backtest, record result, then EXIT." \
    || {
      echo "Claude exited with error (code $?), continuing after cooldown..."
      sleep 5
    }

  echo ""
done
