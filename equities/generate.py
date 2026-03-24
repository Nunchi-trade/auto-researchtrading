"""
Natural Language → Trading Strategy Generator.

Generates a complete strategy.py from a natural language description using Claude,
backtests it, and optionally evolves it.

Usage:
    uv run generate.py "Pairs trading with sector ETFs using z-score entry"
    uv run generate.py --symbols SPY QQQ "Momentum with RSI filter"
    uv run generate.py --refine "Tighten the stops to 2x ATR"
    uv run generate.py --evolve --budget 5
    uv run generate.py --restore
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

EQUITIES_DIR = Path(__file__).parent.resolve()
STRATEGY_PATH = EQUITIES_DIR / "strategy.py"
BACKUP_PATH = EQUITIES_DIR / "strategy_backup.py"
GENERATED_DIR = EQUITIES_DIR / "generated"
PROMPT_TEMPLATE_PATH = EQUITIES_DIR / "GENERATE_PROMPT.md"

MAX_RETRIES = 3

ALLOWED_IMPORTS = {
    "numpy", "np", "pandas", "pd", "scipy", "sklearn",
    "math", "collections", "itertools", "functools",
    "dataclasses", "prepare", "typing", "abc", "enum",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_file(path):
    if path.exists():
        return path.read_text()
    return ""


def backup_strategy():
    if STRATEGY_PATH.exists():
        shutil.copy2(STRATEGY_PATH, BACKUP_PATH)
        print(f"  Backed up strategy to {BACKUP_PATH.name}")


def restore_strategy():
    if BACKUP_PATH.exists():
        shutil.copy2(BACKUP_PATH, STRATEGY_PATH)
        clear_pycache()
        print("  Restored strategy from backup.")
    else:
        print("  No backup found.")


def archive_strategy(code, label=""):
    GENERATED_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"strategy_{ts}_{label}.py" if label else f"strategy_{ts}.py"
    path = GENERATED_DIR / name
    path.write_text(code)
    return path


def clear_pycache():
    cache = EQUITIES_DIR / "__pycache__"
    if cache.exists():
        shutil.rmtree(cache)


def get_current_score(symbols=None, split="val"):
    """Run backtest on current strategy.py and return score."""
    metrics = run_backtest(symbols, split)
    return metrics.get("score", -999.0)


# ---------------------------------------------------------------------------
# Claude CLI interaction
# ---------------------------------------------------------------------------


def call_claude(prompt, timeout=180):
    """Call claude CLI in print mode, return response text."""
    cmd = [
        "claude", "-p",
        "--dangerously-skip-permissions",
        "--model", "sonnet",
        prompt,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {result.stderr[:500]}")
    return result.stdout


# ---------------------------------------------------------------------------
# Code extraction and validation
# ---------------------------------------------------------------------------


def extract_code(response):
    """Extract Python code block from Claude's response."""
    # Try fenced code block
    match = re.search(r"```python\n(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Try unfenced block starting with imports/class
    match = re.search(
        r'((?:""".*?"""\n\n)?(?:import|from).*?class Strategy.*)',
        response, re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    raise ValueError("No strategy code found in Claude response")


def validate_code(code):
    """Validate syntax, structure, and imports. Returns (ok, error_msg)."""
    # Syntax check
    try:
        compile(code, "strategy.py", "exec")
    except SyntaxError as e:
        return False, f"Syntax error on line {e.lineno}: {e.msg}"

    # Structure checks
    if "class Strategy" not in code:
        return False, "Missing 'class Strategy' class definition"
    if "def on_bar" not in code:
        return False, "Missing 'on_bar' method in Strategy class"
    if "def __init__" not in code:
        return False, "Missing '__init__' method in Strategy class"

    # Import check
    for line in code.split("\n"):
        line = line.strip()
        if not (line.startswith("import ") or line.startswith("from ")):
            continue
        parts = line.split()
        if parts[0] == "from":
            mod = parts[1].split(".")[0]
        else:
            mod = parts[1].split(".")[0].split(",")[0]
        if mod not in ALLOWED_IMPORTS:
            return False, f"Disallowed import: '{mod}'. Only allowed: numpy, pandas, scipy, sklearn, prepare, stdlib"

    return True, ""


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------


def run_backtest(symbols=None, split="val"):
    """Run backtest.py and parse results. Returns dict of metrics."""
    clear_pycache()
    cmd = ["uv", "run", "backtest.py"]
    if symbols:
        cmd += ["--symbols"] + symbols
    cmd += ["--split", split]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=180, cwd=str(EQUITIES_DIR),
        )
    except subprocess.TimeoutExpired:
        return {"error": "Backtest timed out (180s)"}

    if result.returncode != 0:
        return {"error": result.stderr[:500], "stdout": result.stdout[-500:]}

    # Parse key: value lines
    metrics = {}
    for line in result.stdout.split("\n"):
        line = line.strip()
        if ":" not in line or line.startswith("#") or line.startswith("Loaded") or line.startswith("Symbols") or line.startswith("---"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        try:
            metrics[key] = float(val)
        except ValueError:
            metrics[key] = val
    return metrics


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_prompt(description, symbols=None, extra_context=""):
    """Build the full prompt from template + description."""
    template = read_file(PROMPT_TEMPLATE_PATH)
    if not template:
        raise RuntimeError(f"Prompt template not found at {PROMPT_TEMPLATE_PATH}")

    # Build reference section
    current_code = read_file(STRATEGY_PATH)
    if current_code:
        reference_section = f"## Reference: Current Strategy\n\n```python\n{current_code}\n```"
    else:
        reference_section = ""

    # Symbol hint
    symbol_hint = ""
    if symbols:
        symbol_hint = f"\n\nTarget symbols: {', '.join(symbols)}"

    full_description = description + symbol_hint
    if extra_context:
        full_description += f"\n\n{extra_context}"

    prompt = template.replace("{description}", full_description)
    prompt = template.replace("{reference_section}", reference_section).replace("{description}", full_description)

    return prompt


def build_refine_prompt(refine_instruction, prev_code, prev_score):
    """Build prompt for refining an existing strategy."""
    template = read_file(PROMPT_TEMPLATE_PATH)

    reference_section = (
        f"## Previously Generated Strategy (score: {prev_score:.4f})\n\n"
        f"```python\n{prev_code}\n```\n\n"
        f"## Refinement Request\n\n{refine_instruction}\n\n"
        f"Modify the strategy above to address this refinement. Output the complete updated file."
    )
    description = f"Refine the strategy above: {refine_instruction}"

    prompt = template.replace("{reference_section}", reference_section).replace("{description}", description)
    return prompt


def build_evolve_prompt(code, score, generation, history=""):
    """Build prompt for one evolution step."""
    template = read_file(PROMPT_TEMPLATE_PATH)

    reference_section = (
        f"## Current Best Strategy (score: {score:.4f})\n\n"
        f"```python\n{code}\n```"
    )
    description = (
        f"Improve this trading strategy. It currently scores {score:.4f}.\n\n"
        f"This is evolution generation {generation}. Suggest ONE specific improvement.\n"
        f"Consider: parameter tuning, new signals, different exits, position sizing, ML features.\n"
        f"Make a single targeted change — do not rewrite the entire strategy."
    )
    if history:
        description += f"\n\nPrevious attempts this session:\n{history}"

    prompt = template.replace("{reference_section}", reference_section).replace("{description}", description)
    return prompt


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------


def generate_strategy(description, symbols=None):
    """Generate strategy from NL description with retries."""
    errors = []

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n  Attempt {attempt}/{MAX_RETRIES}...")

        # Build prompt with accumulated errors
        extra = ""
        if errors:
            extra = "\n\nPREVIOUS ATTEMPTS FAILED — fix these errors:\n" + "\n".join(
                f"  Attempt {i+1}: {e}" for i, e in enumerate(errors)
            )

        try:
            prompt = build_prompt(description, symbols, extra)
            response = call_claude(prompt)
            code = extract_code(response)
        except Exception as e:
            errors.append(f"Generation error: {e}")
            continue

        # Validate
        ok, err = validate_code(code)
        if not ok:
            errors.append(f"Validation: {err}")
            continue

        # Write and test
        STRATEGY_PATH.write_text(code)
        metrics = run_backtest(symbols)

        if "error" in metrics:
            errors.append(f"Runtime crash: {metrics['error'][:300]}")
            continue

        score = metrics.get("score", -999.0)
        if score <= -999:
            errors.append(f"Degenerate score (-999). Must produce >10 trades. Got: {metrics}")
            continue

        # Success
        archive_strategy(code, "gen")
        return code, metrics

    # All retries failed
    restore_strategy()
    print(f"\n  FAILED after {MAX_RETRIES} attempts:")
    for i, e in enumerate(errors):
        print(f"    {i+1}. {e}")
    return None, {"error": "All retries failed"}


def refine_strategy(instruction, symbols=None):
    """Refine the current strategy based on NL instruction."""
    prev_code = read_file(STRATEGY_PATH)
    prev_score = get_current_score(symbols)

    errors = []
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n  Refine attempt {attempt}/{MAX_RETRIES}...")

        extra_errors = ""
        if errors:
            extra_errors = "\n\nFix these errors from previous attempts:\n" + "\n".join(errors)

        try:
            prompt = build_refine_prompt(instruction + extra_errors, prev_code, prev_score)
            response = call_claude(prompt)
            code = extract_code(response)
        except Exception as e:
            errors.append(str(e))
            continue

        ok, err = validate_code(code)
        if not ok:
            errors.append(err)
            continue

        STRATEGY_PATH.write_text(code)
        metrics = run_backtest(symbols)

        if "error" in metrics:
            errors.append(metrics["error"][:300])
            continue

        score = metrics.get("score", -999.0)
        if score <= -999:
            errors.append(f"Degenerate score. Metrics: {metrics}")
            continue

        archive_strategy(code, "refine")
        return code, metrics

    restore_strategy()
    print(f"\n  Refinement FAILED after {MAX_RETRIES} attempts.")
    return None, {"error": "All retries failed"}


def evolve_strategy(symbols=None, budget=5.0, split="val"):
    """Run evolution loop using Claude to suggest improvements."""
    best_code = read_file(STRATEGY_PATH)
    best_score = get_current_score(symbols, split)
    print(f"\n  Starting evolution. Current score: {best_score:.4f}")
    print(f"  Budget: ${budget:.2f}")

    history_lines = []
    generation = 0

    while True:
        generation += 1
        history = "\n".join(history_lines[-10:])  # last 10 attempts

        print(f"\n  --- Generation {generation} ---")
        try:
            prompt = build_evolve_prompt(best_code, best_score, generation, history)
            response = call_claude(prompt, timeout=120)
            code = extract_code(response)
        except Exception as e:
            msg = f"Gen {generation}: generation error: {e}"
            print(f"  {msg}")
            history_lines.append(msg)
            continue

        ok, err = validate_code(code)
        if not ok:
            msg = f"Gen {generation}: validation failed: {err}"
            print(f"  {msg}")
            history_lines.append(msg)
            continue

        STRATEGY_PATH.write_text(code)
        metrics = run_backtest(symbols, split)

        score = metrics.get("score", -999.0)
        if "error" in metrics:
            msg = f"Gen {generation}: crash: {metrics['error'][:100]}"
            print(f"  {msg}")
            history_lines.append(msg)
            STRATEGY_PATH.write_text(best_code)
            continue

        delta = score - best_score
        if score > best_score:
            best_score = score
            best_code = code
            archive_strategy(code, f"evo_g{generation}")
            msg = f"Gen {generation}: score={score:.4f} (+{delta:.4f}) NEW BEST"
            print(f"  >>> {msg}")
        else:
            STRATEGY_PATH.write_text(best_code)
            msg = f"Gen {generation}: score={score:.4f} ({delta:+.4f}) reverted"
            print(f"  {msg}")

        history_lines.append(msg)

    print(f"\n  Evolution complete. Best score: {best_score:.4f}")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def print_results(metrics, prev_score=None):
    """Print backtest results."""
    score = metrics.get("score", -999.0)
    print("\n" + "=" * 50)
    print("  STRATEGY RESULTS")
    print("=" * 50)
    print(f"  Score:        {score:.4f}")
    print(f"  Sharpe:       {metrics.get('sharpe', 0):.4f}")
    print(f"  Return:       {metrics.get('total_return_pct', 0):+.2f}%")
    print(f"  Max DD:       {metrics.get('max_drawdown_pct', 0):.2f}%")
    print(f"  Trades:       {int(metrics.get('num_trades', 0))}")
    print(f"  Win Rate:     {metrics.get('win_rate_pct', 0):.1f}%")
    print(f"  Profit Factor:{metrics.get('profit_factor', 0):.2f}")
    print(f"  Time:         {metrics.get('backtest_seconds', 0):.1f}s")

    if prev_score is not None:
        delta = score - prev_score
        label = "BETTER" if delta > 0 else "WORSE" if delta < 0 else "SAME"
        print(f"\n  Previous:     {prev_score:.4f}")
        print(f"  Delta:        {delta:+.4f} ({label})")

    print("=" * 50)
    print("\n  Next steps:")
    print('    uv run generate.py --refine "adjust X"')
    print("    uv run generate.py --evolve --budget 5")
    print("    uv run generate.py --restore")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate trading strategies from natural language"
    )
    parser.add_argument(
        "description", nargs="?", default=None,
        help="Natural language strategy description",
    )
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--split", default="val", choices=["train", "val", "test"])
    parser.add_argument("--refine", type=str, help="Refine the current strategy")
    parser.add_argument("--evolve", action="store_true", help="Start evolution loop")
    parser.add_argument("--budget", type=float, default=5.0, help="Evolution budget in USD")
    parser.add_argument("--restore", action="store_true", help="Restore backup strategy")
    parser.add_argument("--dry-run", action="store_true", help="Show prompt without calling Claude")
    args = parser.parse_args()

    # Restore mode
    if args.restore:
        restore_strategy()
        score = get_current_score(args.symbols, args.split)
        print(f"  Restored. Score: {score:.4f}")
        return

    # Evolve mode
    if args.evolve:
        evolve_strategy(args.symbols, args.budget, args.split)
        return

    # Refine mode
    if args.refine:
        prev_score = get_current_score(args.symbols, args.split)
        print(f"Refining strategy (current score: {prev_score:.4f})...")
        backup_strategy()
        code, metrics = refine_strategy(args.refine, args.symbols)
        if code:
            print_results(metrics, prev_score)
        return

    # Generate mode
    if not args.description:
        parser.print_help()
        return

    prev_score = get_current_score(args.symbols, args.split) if STRATEGY_PATH.exists() else None
    print(f"Generating strategy from: \"{args.description}\"")
    if prev_score is not None:
        print(f"  Current score: {prev_score:.4f}")

    if args.dry_run:
        prompt = build_prompt(args.description, args.symbols)
        print("\n--- PROMPT ---")
        print(prompt)
        return

    backup_strategy()
    code, metrics = generate_strategy(args.description, args.symbols)
    if code:
        print_results(metrics, prev_score)


if __name__ == "__main__":
    main()
