# Upbit Return/Risk Optimization Design

**Context**

균형 최적화 라운드로 `train/val/test` 점수 편차는 크게 줄였다. 현재 60분봉 기준 기본값은 `train 1.630 / val 2.324 / test 1.620`, `drawdown 7.8 / 3.4 / 4.2`다. 이제 병목은 방어보다 수익 회복이다.

**Goal**

수익을 더 끌어올리되 어느 split에서도 drawdown이 급격히 악화되지 않도록, 출구 민감도와 평가 목적함수를 함께 재조정한다.

**Design**

1. `upbit_strategy.py`에서 출구 민감도 중 두 축만 파라미터화한다.
   - `RECENT_HIGH_BUFFER`
   - `STOCH_EXIT_THRESHOLD`
2. `upbit_balanced_research.py`에 `return/risk` 목적함수를 추가한다.
3. `scripts/upbit_balanced_search.py`는 목적함수 선택을 받도록 확장한다.
4. 탐색은 240분봉 coarse shortlist 후, 상위 3개만 60분봉 full 평가한다.

**Return/Risk Objective**

- 하드 컷:
  - 어떤 split이든 `max_drawdown_pct > 12`
  - `test total_return_pct <= 0`
- 랭킹:
  - `worst_split_return_to_drawdown = min(return_pct / max(drawdown_pct, 1.0))`
  - `mean_return` 가산
  - split 간 수익 편차 패널티

**Search Scope**

- `BASE_POSITION_PCT`
- `COOLDOWN_BARS`
- `MAX_HOLD_BARS`
- `MIN_BEAR_VOTES`
- `RECENT_HIGH_BUFFER`
- `STOCH_EXIT_THRESHOLD`

사이징은 지난 라운드 결과를 유지하고, 이번에는 출구 완화가 수익 회복에 주는 영향만 본다.
