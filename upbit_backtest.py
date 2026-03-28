"""
Upbit 현물 백테스트 진입점.
Usage: uv run upbit_backtest.py
"""
import time
from upbit_prepare import load_upbit_data, run_upbit_backtest, compute_upbit_score

t_start = time.time()

from upbit_strategy import Strategy

strategy = Strategy()
data = load_upbit_data("val")

if not data:
    print("데이터 없음. 먼저 실행하세요: uv run upbit_prepare_run.py")
    raise SystemExit(1)

print(f"로드: {sum(len(df) for df in data.values())} 봉 / {len(data)} 심볼")
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
