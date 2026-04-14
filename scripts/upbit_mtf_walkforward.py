import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from upbit_mtf_research import evaluate_walkforward_parameter_set, load_search_datasets
from upbit_mtf_strategy import DEFAULT_MTF_PARAMS


def _format_window(window: dict) -> str:
    train = window["train_metrics"]
    test = window["test_metrics"]
    return (
        f"{window['index']:>2}. "
        f"train=[{window['train_start_ts']}..{window['train_end_ts']}] "
        f"test=[{window['test_start_ts']}..{window['test_end_ts']}] "
        f"train_excess={train['excess_return_pct']:.1f}% "
        f"train_dd={train['drawdown_pct']:.1f}% "
        f"test_excess={test['excess_return_pct']:.1f}% "
        f"test_dd={test['drawdown_pct']:.1f}% "
        f"trades={test['trades']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-bars", type=int, default=24 * 365 * 2, help="학습(과거 컨텍스트) 구간 bar 수")
    parser.add_argument("--test-bars", type=int, default=24 * 180, help="검증 구간 bar 수")
    parser.add_argument("--step-bars", type=int, default=24 * 180, help="윈도우 이동 bar 수")
    parser.add_argument("--interval", type=int, default=60, help="실행 기준 interval")
    args = parser.parse_args()

    datasets = load_search_datasets(base_interval=args.interval)
    result = evaluate_walkforward_parameter_set(
        params=DEFAULT_MTF_PARAMS,
        datasets=datasets,
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        step_bars=args.step_bars,
        base_interval=args.interval,
    )

    aggregate = result["aggregate"]
    print("strategy: upbit_mtf_strategy (walk-forward)")
    print(f"interval: {args.interval}m")
    print(f"train_bars: {args.train_bars}")
    print(f"test_bars: {args.test_bars}")
    print(f"step_bars: {args.step_bars}")
    print(f"windows: {aggregate['num_windows']}")
    print(f"mean_test_excess: {aggregate['mean_test_excess_return_pct']:.2f}%")
    print(f"min_test_excess: {aggregate['min_test_excess_return_pct']:.2f}%")
    print(f"max_test_dd: {aggregate['max_test_drawdown_pct']:.2f}%")
    print(f"positive_test_ratio: {aggregate['positive_test_window_ratio']:.2%}")
    print("--- windows ---")
    for window in result["windows"]:
        print(_format_window(window))


if __name__ == "__main__":
    main()
