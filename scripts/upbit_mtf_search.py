import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from upbit_mtf_research import DEFAULT_MTF_PARAMETER_GRID, search_parameter_grid


def _format_row(rank: int, result: dict) -> str:
    full = result["metrics"]["full"]
    test = result["metrics"]["test"]
    return (
        f"{rank:>2}. objective={result['objective_score']:.2f} "
        f"full_ret={full['strategy_return_pct']:.1f}% "
        f"full_bh={full['buy_hold_return_pct']:.1f}% "
        f"full_excess={full['excess_return_pct']:.1f}% "
        f"full_dd={full['drawdown_pct']:.1f}% "
        f"test_ret={test['strategy_return_pct']:.1f}% "
        f"test_bh={test['buy_hold_return_pct']:.1f}% "
        f"test_excess={test['excess_return_pct']:.1f}% "
        f"trades={full['trades']} "
        f"params={result['params']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=10, help="출력할 상위 조합 수")
    parser.add_argument("--progress-every", type=int, default=10, help="진행 로그 주기")
    args = parser.parse_args()

    total_combos = 1
    for values in DEFAULT_MTF_PARAMETER_GRID.values():
        total_combos *= len(values)

    print("strategy: upbit_mtf_strategy")
    print("intervals: 10m/20m/30m/60m/240m with 60m execution")
    print(f"combos: {total_combos}")
    results = search_parameter_grid(progress_every=args.progress_every)
    print("--- top results ---")
    for rank, result in enumerate(results[:args.top], start=1):
        print(_format_row(rank, result))


if __name__ == "__main__":
    main()
