#!/usr/bin/env python3
"""Compare two backtest snapshots signal-by-signal.

Usage:
    python harness/compare.py baseline.json refactored.json

Exit code 0 = identical, 1 = divergence found.
"""

import json
import sys
import math

FLOAT_TOLERANCE = 1e-4  # signals/trades rounded to 6dp, this catches real diffs


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def floats_equal(a: float, b: float) -> bool:
    if a == b:
        return True
    return math.isclose(a, b, rel_tol=FLOAT_TOLERANCE, abs_tol=FLOAT_TOLERANCE)


def compare_signals(a: list, b: list) -> list[str]:
    errors = []
    if len(a) != len(b):
        errors.append(f"Signal count differs: {len(a)} vs {len(b)}")

    for i, (sa, sb) in enumerate(zip(a, b)):
        diffs = []
        for key in ("bar", "symbol", "target_position", "current_position"):
            va, vb = sa.get(key), sb.get(key)
            if isinstance(va, float) and isinstance(vb, float):
                if not floats_equal(va, vb):
                    diffs.append(f"{key}: {va} vs {vb}")
            elif va != vb:
                diffs.append(f"{key}: {va} vs {vb}")
        if diffs:
            errors.append(f"Signal #{i}: {', '.join(diffs)}")
            if len(errors) >= 20:
                errors.append("... (truncated, too many diffs)")
                break

    return errors


def compare_trades(a: list, b: list) -> list[str]:
    errors = []
    if len(a) != len(b):
        errors.append(f"Trade count differs: {len(a)} vs {len(b)}")

    for i, (ta, tb) in enumerate(zip(a, b)):
        diffs = []
        for key in ("action", "symbol", "delta", "exec_price", "pnl"):
            va, vb = ta.get(key), tb.get(key)
            if isinstance(va, float) and isinstance(vb, float):
                if not floats_equal(va, vb):
                    diffs.append(f"{key}: {va} vs {vb}")
            elif va != vb:
                diffs.append(f"{key}: {va} vs {vb}")
        if diffs:
            errors.append(f"Trade #{i}: {', '.join(diffs)}")
            if len(errors) >= 20:
                errors.append("... (truncated, too many diffs)")
                break

    return errors


def compare_equity(a: list, b: list) -> list[str]:
    errors = []
    if len(a) != len(b):
        errors.append(f"Equity curve length differs: {len(a)} vs {len(b)}")

    first_diff = None
    diff_count = 0
    for i, (ea, eb) in enumerate(zip(a, b)):
        if not floats_equal(ea, eb):
            diff_count += 1
            if first_diff is None:
                first_diff = i

    if diff_count > 0:
        assert first_diff is not None
        errors.append(
            f"Equity curve: {diff_count} divergent points, "
            f"first at index {first_diff} ({a[first_diff]} vs {b[first_diff]})"
        )

    return errors


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <baseline.json> <refactored.json>")
        sys.exit(2)

    baseline = load(sys.argv[1])
    refactored = load(sys.argv[2])

    print(f"Baseline:   {sys.argv[1]}")
    print(f"Refactored: {sys.argv[2]}")
    print(f"Strategy:   {baseline.get('strategy')} / {refactored.get('strategy')}")
    print(f"Interval:   {baseline.get('interval')} / {refactored.get('interval')}")
    print()

    all_errors = []

    # Compare top-level metrics
    for key in ("bars_processed", "num_trades"):
        if baseline.get(key) != refactored.get(key):
            all_errors.append(f"{key}: {baseline.get(key)} vs {refactored.get(key)}")

    for key in ("final_equity", "total_return_pct", "max_drawdown_pct"):
        if not floats_equal(baseline.get(key, 0), refactored.get(key, 0)):
            all_errors.append(f"{key}: {baseline.get(key)} vs {refactored.get(key)}")

    # Compare signals
    sig_errors = compare_signals(
        baseline.get("signals", []), refactored.get("signals", [])
    )
    all_errors.extend(sig_errors)

    # Compare trades
    trade_errors = compare_trades(
        baseline.get("trades", []), refactored.get("trades", [])
    )
    all_errors.extend(trade_errors)

    # Compare equity curve
    eq_errors = compare_equity(
        baseline.get("equity_curve", []), refactored.get("equity_curve", [])
    )
    all_errors.extend(eq_errors)

    if not all_errors:
        sig_count = len(baseline.get("signals", []))
        trade_count = len(baseline.get("trades", []))
        eq_count = len(baseline.get("equity_curve", []))
        print(
            f"PASS: {sig_count} signals, {trade_count} trades, "
            f"{eq_count} equity points all match."
        )
        sys.exit(0)
    else:
        print(f"FAIL: {len(all_errors)} difference(s) found:\n")
        for err in all_errors:
            print(f"  - {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
