# Upbit Entry Filter Optimization Design

**Context**

출구 민감도 조정과 `return_risk` 목적함수 실험까지 마쳤지만, 60분봉 full check에서는 현재 기본값이 가장 안정적이었다. 다음 병목은 출구가 아니라 진입 빈도와 추세 필터 강도다.

**Goal**

수익을 더 끌어올리면서 drawdown은 현재 수준을 유지하기 위해, 진입/추세 필터 강도를 좁은 범위에서 재탐색한다.

**Design**

1. `upbit_strategy.py`에서 진입 관련 세 축만 파라미터화한다.
   - `TREND_FILTER_BARS`
   - `SMA_SLOPE_THRESHOLD`
   - `ADX_ENTRY_THRESHOLD`
2. 기존 `return_risk` 목적함수는 그대로 유지한다.
3. coarse search는 240분봉에서 소규모 그리드로 돌리고, 상위 3개만 60분봉 full check로 올린다.

**Search Scope**

- `TREND_FILTER_BARS`: 짧게 하면 진입 기회는 늘지만 추세 품질이 약해질 수 있다.
- `SMA_SLOPE_THRESHOLD`: 낮추면 완만한 상승 추세도 허용한다.
- `ADX_ENTRY_THRESHOLD`: 낮추면 약한 추세에도 진입한다.

**Success Criteria**

- 진입 파라미터가 테스트로 고정된다.
- 240분봉 coarse shortlist가 나온다.
- 60분봉 full check에서 현재 기본값보다 높은 `return_risk` 또는 더 나은 수익/DD 조합이 나오면 기본값을 교체한다.
