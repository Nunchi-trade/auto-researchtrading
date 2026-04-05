# Upbit Balanced Search Design

**Context**

현재 `upbit_strategy.py`는 `val` 기준으로 튜닝된 상태라 `train/val/test` 간 성능 편차가 크다. 최근 리스크 우선 조정으로 `test`와 `train`은 개선됐지만, 단일 split 최적화 구조 자체는 그대로 남아 있다.

**Goal**

`train/val/test`를 동시에 고려하는 균형 목적함수와 자동 탐색 스크립트를 추가해, 한 구간만 높은 조합보다 세 구간이 모두 버티는 조합을 우선 선택한다.

**Design**

1. `upbit_strategy.py`는 탐색 대상 파라미터만 오버라이드 가능하게 바꾼다.
2. `upbit_balanced_research.py`는 균형 목적함수, 파라미터 그리드 생성, 단일 조합 평가 로직을 담당한다.
3. `scripts/upbit_balanced_search.py`는 CLI 진입점으로 상위 조합을 표 형태로 출력한다.
4. 목적함수는 `worst_split_score`를 가장 중시하고 `mean_score`를 보조로 사용하며, 최고/최저 split 간 편차가 클수록 패널티를 부여한다.

**Search Scope**

- `BASE_POSITION_PCT`
- `SIZE_TARGET_VOL`
- `MIN_POSITION_SCALE`
- `COOLDOWN_BARS`
- `MAX_HOLD_BARS`
- `MIN_BEAR_VOTES`

진입 신호 구조와 주요 지표 파라미터는 이번 라운드에서 건드리지 않는다. 이번 연구의 목적은 리스크/출구 민감도 조정이 균형 성능에 미치는 영향을 빠르게 확인하는 것이다.

**Success Criteria**

- 자동 탐색 스크립트가 여러 조합을 평가하고 상위 조합을 출력한다.
- 새 목적함수 테스트가 존재한다.
- 전략 파라미터 오버라이드가 테스트로 고정된다.
- 최종 기본값은 기존 대비 `train/val/test` 균형 지표가 개선된 조합만 반영한다.
