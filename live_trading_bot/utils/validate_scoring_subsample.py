"""Validation script for tune_15m.py: scoring function math + subsample ranking preservation.

Runs two test suites:
  1. Scoring function mathematical correctness (10 synthetic cases)
  2. Subsample ranking preservation on real 15m candle data (5 param sets)
"""

import sys
import math
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from data_pipeline.backtest.tune_15m import (
    score_result,
    subsample_data,
    run_once,
    reset_params,
)
from data_pipeline.backtest.backtest_interval import load_data


# ============================================================================
# VALIDATION 1: Scoring Function Mathematical Correctness
# ============================================================================
def test_scoring():
    """Test score_result() against hand-calculated expected values for 10 cases."""
    print("=" * 80)
    print("VALIDATION 1: Scoring Function Mathematical Correctness")
    print("=" * 80)
    print()
    print("Formula: score = ret/dd * trade_confidence * pf_bonus")
    print("  where dd = max(max_drawdown_pct, 0.01)")
    print("        trade_confidence = min(num_closes / 20, 1.0)")
    print("        pf_bonus = 1 + max(0, pf - 2) * 0.1")
    print()

    test_cases = [
        {
            "name": "Case 1: Good strategy",
            "input": {
                "total_return_pct": 300.0,
                "max_drawdown_pct": 10.0,
                "num_closes": 50,
                "profit_factor": 3.0,
            },
            "expected": 33.0,
            "math": "ret_dd=300/10=30, tc=min(50/20,1)=1.0, pf_bonus=1+max(0,3-2)*0.1=1.1 => 30*1.0*1.1=33.0",
        },
        {
            "name": "Case 2: Few trades (penalized)",
            "input": {
                "total_return_pct": 200.0,
                "max_drawdown_pct": 5.0,
                "num_closes": 5,
                "profit_factor": 2.5,
            },
            "expected": 10.5,
            "math": "ret_dd=200/5=40, tc=min(5/20,1)=0.25, pf_bonus=1+max(0,2.5-2)*0.1=1.05 => 40*0.25*1.05=10.5",
        },
        {
            "name": "Case 3: Low profit factor (no bonus)",
            "input": {
                "total_return_pct": 100.0,
                "max_drawdown_pct": 8.0,
                "num_closes": 30,
                "profit_factor": 1.5,
            },
            "expected": 12.5,
            "math": "ret_dd=100/8=12.5, tc=min(30/20,1)=1.0, pf_bonus=1+max(0,1.5-2)*0.1=1.0 => 12.5*1.0*1.0=12.5",
        },
        {
            "name": "Case 4: Zero DD edge case",
            "input": {
                "total_return_pct": 50.0,
                "max_drawdown_pct": 0.0,
                "num_closes": 20,
                "profit_factor": 4.0,
            },
            "expected": 6000.0,
            "math": "dd=max(0,0.01)=0.01, ret_dd=50/0.01=5000, tc=1.0, pf_bonus=1+max(0,4-2)*0.1=1.2 => 5000*1.0*1.2=6000.0",
        },
        {
            "name": "Case 5: Negative return",
            "input": {
                "total_return_pct": -20.0,
                "max_drawdown_pct": 15.0,
                "num_closes": 10,
                "profit_factor": 0.5,
            },
            "expected": -20.0 / 15.0 * 0.5 * 1.0,  # -0.6666...
            "math": "ret_dd=-20/15=-1.333, tc=min(10/20,1)=0.5, pf_bonus=1+max(0,0.5-2)*0.1=1.0 => -1.333*0.5*1.0=-0.667",
        },
        {
            "name": "Case 6: Exactly 20 closes (boundary)",
            "input": {
                "total_return_pct": 150.0,
                "max_drawdown_pct": 12.0,
                "num_closes": 20,
                "profit_factor": 2.0,
            },
            "expected": 12.5,
            "math": "ret_dd=150/12=12.5, tc=min(20/20,1)=1.0, pf_bonus=1+max(0,2-2)*0.1=1.0 => 12.5*1.0*1.0=12.5",
        },
        {
            "name": "Case 7: High PF, many trades",
            "input": {
                "total_return_pct": 500.0,
                "max_drawdown_pct": 20.0,
                "num_closes": 100,
                "profit_factor": 5.0,
            },
            "expected": 32.5,
            "math": "ret_dd=500/20=25, tc=1.0, pf_bonus=1+max(0,5-2)*0.1=1.3 => 25*1.0*1.3=32.5",
        },
        {
            "name": "Case 8: Missing num_closes (uses num_trades)",
            "input": {
                "total_return_pct": 100.0,
                "max_drawdown_pct": 5.0,
                "num_trades": 40,
                "profit_factor": 2.0,
            },
            "expected": 20.0,
            "math": "num_closes=r.get('num_closes',r.get('num_trades',0))=40, tc=1.0, ret_dd=100/5=20, pf_bonus=1.0 => 20.0",
        },
        {
            "name": "Case 9: Zero closes",
            "input": {
                "total_return_pct": 0.0,
                "max_drawdown_pct": 1.0,
                "num_closes": 0,
                "profit_factor": 0.0,
            },
            "expected": 0.0,
            "math": "ret_dd=0/1=0, tc=0/20=0, pf_bonus=1+max(0,0-2)*0.1=1.0 => 0*0*1.0=0.0",
        },
        {
            "name": "Case 10: Missing profit_factor",
            "input": {
                "total_return_pct": 80.0,
                "max_drawdown_pct": 4.0,
                "num_closes": 25,
            },
            "expected": 20.0,
            "math": "pf=r.get('profit_factor',1.0)=1.0, ret_dd=80/4=20, tc=1.0, pf_bonus=1+max(0,1-2)*0.1=1.0 => 20.0",
        },
    ]

    passed = 0
    failed = 0
    atol = 1e-10

    for i, tc in enumerate(test_cases, 1):
        actual = score_result(tc["input"])
        expected = tc["expected"]
        match = math.isclose(actual, expected, abs_tol=atol)
        status = "PASS" if match else "FAIL"

        if match:
            passed += 1
        else:
            failed += 1

        print(f"[{status}] {tc['name']}")
        print(f"  Input:    {tc['input']}")
        print(f"  Math:     {tc['math']}")
        print(f"  Expected: {expected}")
        print(f"  Actual:   {actual}")
        if not match:
            print(f"  Diff:     {abs(actual - expected):.2e}")
        print()

    print("-" * 80)
    print(f"VALIDATION 1 RESULT: {passed}/{len(test_cases)} passed, {failed} failed")
    if failed == 0:
        print("ALL SCORING TESTS PASSED")
    else:
        print("SOME SCORING TESTS FAILED — see details above")
    print()
    return failed == 0


# ============================================================================
# VALIDATION 2: Subsample Ranking Preservation
# ============================================================================
def test_subsample_ranking():
    """Test that subsample ranking correlates with full-data ranking."""
    print("=" * 80)
    print("VALIDATION 2: Subsample Ranking Preservation")
    print("=" * 80)
    print()

    # Load real 15m candle data
    data_dir = str(
        Path(__file__).resolve().parent.parent / "backtest_data" / "15m_candles"
    )
    print(f"Loading data from: {data_dir}")
    full_data = load_data(interval="15m", data_dir=data_dir)
    if not full_data:
        print("ERROR: No data loaded — cannot run subsample test")
        return False

    total_bars = sum(len(df) for df in full_data.values())
    symbols = list(full_data.keys())
    print(f"Loaded {total_bars} bars across {len(symbols)} symbols: {symbols}")

    # Create subsampled data
    sub_data = subsample_data(full_data, every_n=4)
    sub_bars = sum(len(df) for df in sub_data.values())
    print(
        f"Subsampled: {sub_bars} bars (every 4th bar, ~{total_bars / sub_bars:.1f}x speedup)"
    )
    print()

    # Define 5 parameter sets
    param_sets = [
        {"BASE_POSITION_PCT": 2.0},  # default
        {"BASE_POSITION_PCT": 4.0},  # was best in phase 1
        {"ATR_STOP_MULT": 3.0},
        {"ATR_STOP_MULT": 8.0},
        {"COOLDOWN_BARS": 2},
    ]

    results = []
    for i, params in enumerate(param_sets):
        label = ", ".join(f"{k}={v}" for k, v in params.items())

        # Run on full data
        print(f"  [{i + 1}/5] Running {label} on FULL data...")
        full_result = run_once(full_data, params)
        if "error" in full_result:
            print(f"    ERROR on full data: {full_result['error']}")
            continue
        full_score = full_result["_score"]

        # Run on subsampled data
        print(f"  [{i + 1}/5] Running {label} on SUBSAMPLED data...")
        sub_result = run_once(sub_data, params)
        if "error" in sub_result:
            print(f"    ERROR on subsampled data: {sub_result['error']}")
            continue
        sub_score = sub_result["_score"]

        results.append(
            {
                "params": params,
                "label": label,
                "full_score": full_score,
                "sub_score": sub_score,
                "full_return": full_result.get("total_return_pct", 0),
                "full_dd": full_result.get("max_drawdown_pct", 0),
                "full_pf": full_result.get("profit_factor", 0),
                "full_trades": full_result.get("num_trades", 0),
            }
        )
        print(f"    Full={full_score:.4f}  Sub={sub_score:.4f}")
        print()

    if len(results) < 2:
        print("ERROR: Not enough valid results to rank — cannot run subsample test")
        return False

    # Compute rankings (by score, descending = rank 1 is best)
    sorted_by_full = sorted(results, key=lambda x: x["full_score"], reverse=True)
    sorted_by_sub = sorted(results, key=lambda x: x["sub_score"], reverse=True)

    full_ranks = {r["label"]: rank + 1 for rank, r in enumerate(sorted_by_full)}
    sub_ranks = {r["label"]: rank + 1 for rank, r in enumerate(sorted_by_sub)}

    # Print ranking table
    print()
    print("-" * 90)
    print("RANKING TABLE")
    print("-" * 90)
    print(
        f"{'Params':<30} {'Full_Score':>12} {'Sub_Score':>12} {'Full_Rank':>10} {'Sub_Rank':>10}"
    )
    print("-" * 90)
    for r in results:
        print(
            f"{r['label']:<30} {r['full_score']:>12.4f} {r['sub_score']:>12.4f} "
            f"{full_ranks[r['label']]:>10d} {sub_ranks[r['label']]:>10d}"
        )
    print("-" * 90)
    print()

    # Check: is the best on subsampled among top-2 on full data?
    best_sub_label = sorted_by_sub[0]["label"]
    best_sub_full_rank = full_ranks[best_sub_label]
    top2_preserved = best_sub_full_rank <= 2

    print(
        f"Best on subsampled: {best_sub_label} (full data rank: {best_sub_full_rank})"
    )
    print(f"Subsample best in top-2 on full data: {'YES' if top2_preserved else 'NO'}")
    print()

    # Spearman rank correlation
    n = len(results)
    labels = [r["label"] for r in results]
    fr = [full_ranks[label] for label in labels]
    sr = [sub_ranks[label] for label in labels]

    # Spearman = 1 - (6 * sum(d_i^2)) / (n * (n^2 - 1))
    d_sq_sum = sum((f - s) ** 2 for f, s in zip(fr, sr))
    if n > 1:
        spearman = 1.0 - (6.0 * d_sq_sum) / (n * (n**2 - 1))
    else:
        spearman = float("nan")

    print(f"Spearman rank correlation: {spearman:.4f}")
    print("  (1.0 = perfect agreement, 0.0 = no correlation, -1.0 = inverse)")
    print()

    # Verdict
    spearman_ok = spearman >= 0.5  # reasonable threshold
    overall_pass = top2_preserved and spearman_ok

    print("-" * 90)
    print("VALIDATION 2 RESULT:")
    print(f"  Top-2 preservation: {'PASS' if top2_preserved else 'FAIL'}")
    print(
        f"  Spearman rho={spearman:.4f}: {'PASS (>=0.5)' if spearman_ok else 'FAIL (<0.5)'}"
    )
    print(f"  Overall: {'PASS' if overall_pass else 'FAIL'}")
    print()

    reset_params()
    return overall_pass


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    v1_pass = test_scoring()
    v2_pass = test_subsample_ranking()

    print("=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    print(f"  Validation 1 (Scoring Math):       {'PASS' if v1_pass else 'FAIL'}")
    print(f"  Validation 2 (Subsample Ranking):   {'PASS' if v2_pass else 'FAIL'}")
    all_pass = v1_pass and v2_pass
    print(
        f"  Overall:                            {'ALL PASS' if all_pass else 'SOME FAILED'}"
    )
    print()
    sys.exit(0 if all_pass else 1)
