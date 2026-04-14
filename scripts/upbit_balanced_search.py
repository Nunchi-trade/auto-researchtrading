import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from upbit_balanced_research import (
    DEFAULT_PARAMETER_GRID,
    RETURN_RISK_PARAMETER_GRID,
    search_parameter_grid,
)


def _format_row(rank: int, result: dict) -> str:
    metrics = result["metrics"]
    return (
        f"{rank:>2}. objective={result['objective_score']:.3f} "
        f"balanced={result['balanced_score']:.3f} "
        f"rr={result['return_risk_score']:.3f} "
        f"train={metrics['train']['score']:.3f} "
        f"val={metrics['val']['score']:.3f} "
        f"test={metrics['test']['score']:.3f} "
        f"dd(train/val/test)="
        f"{metrics['train']['drawdown_pct']:.1f}/"
        f"{metrics['val']['drawdown_pct']:.1f}/"
        f"{metrics['test']['drawdown_pct']:.1f} "
        f"params={result['params']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=60, help="봉 단위 분")
    parser.add_argument("--top", type=int, default=10, help="출력할 상위 조합 수")
    parser.add_argument("--progress-every", type=int, default=25, help="진행 로그 주기")
    parser.add_argument(
        "--objective",
        choices=["balanced", "return_risk"],
        default="balanced",
        help="탐색 목적함수",
    )
    args = parser.parse_args()

    parameter_grid = DEFAULT_PARAMETER_GRID if args.objective == "balanced" else RETURN_RISK_PARAMETER_GRID
    total_combos = 1
    for values in parameter_grid.values():
        total_combos *= len(values)

    print(f"objective: {args.objective}")
    print(f"interval: {args.interval}m")
    print(f"combos: {total_combos}")
    results = search_parameter_grid(
        interval_minutes=args.interval,
        progress_every=args.progress_every,
        objective=args.objective,
    )
    print("--- top results ---")
    for rank, result in enumerate(results[:args.top], start=1):
        print(_format_row(rank, result))


if __name__ == "__main__":
    main()
