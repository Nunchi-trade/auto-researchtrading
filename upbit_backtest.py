"""
Upbit 현물 백테스트 진입점.
Usage:
    uv run upbit_backtest.py                       # 기본: val 60분봉
    uv run upbit_backtest.py --split train         # train 구간
    uv run upbit_backtest.py --split test          # test 구간 (최종 평가용)
    uv run upbit_backtest.py --interval 10         # 10분봉
"""
import time
import argparse
from upbit_prepare import load_upbit_data, run_upbit_backtest, compute_upbit_score

parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=60,
                    help="봉 단위 분 (1/5/10/15/30/60/240, 기본: 60)")
parser.add_argument("--split", type=str, default="val",
                    choices=["train", "val", "test"],
                    help="데이터 구간 (train/val/test, 기본: val)")
args = parser.parse_args()

t_start = time.time()

from upbit_strategy import Strategy

strategy = Strategy()
data = load_upbit_data(args.split, interval_minutes=args.interval)

if not data:
    print("데이터 없음. 먼저 실행하세요: uv run upbit_prepare_run.py")
    raise SystemExit(1)

print(f"구간: {args.split}")
print(f"봉 단위: {args.interval}분")
print(f"로드: {sum(len(df) for df in data.values()):,} 봉 / {len(data)} 심볼")
print(f"심볼: {list(data.keys())}")

result = run_upbit_backtest(strategy, data)
score  = compute_upbit_score(result)

print("---")
print(f"score:              {score:.6f}")
print(f"sharpe:             {result.sharpe:.6f}")
print(f"total_return_pct:   {result.total_return_pct:.6f}")
print(f"max_drawdown_pct:   {result.max_drawdown_pct:.6f}")
print(f"num_trades:         {result.num_trades}")
print(f"win_rate_pct:       {result.win_rate_pct:.6f}")
print(f"profit_factor:      {result.profit_factor:.6f}")
print(f"annual_turnover:    {result.annual_turnover:.2f}")
print(f"total_seconds:      {time.time() - t_start:.1f}")
