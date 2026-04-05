# Upbit MTF State Machine Design

**Context**

현재 60분봉 기본 전략은 `MDD`를 낮게 유지하지만, `2017-09-01`부터 `2026-03-29`까지의 전체 기간 총수익률은 약 `230.05%`로 `KRW-BTC buy-and-hold 2292.93%`에 크게 못 미친다. 다음 라운드는 절대 수익 회복이 우선이며, 사용자는 `MDD 20%`까지는 허용했다.

**Goal**

장기 상승장은 최대한 따라가고, 약세 전환에서는 비중을 줄이거나 이탈하는 다중 타임프레임 트레이딩 전략을 새로 만들고 자동화 탐색으로 기본 조합을 고른다.

**Design**

1. 기존 `upbit_strategy.py`는 유지하고, 별도 `upbit_mtf_strategy.py`를 추가한다.
2. 새 전략은 `flat / reduced / full_long` 상태기계를 사용한다.
3. 매크로 레짐은 `240m` 데이터를 기반으로 `3D, 5D, 10D, 20D, 60D, 120D` 창에서 계산한다.
4. 마이크로 타이밍은 `10m, 20m, 30m, 60m, 240m` 데이터에서 동시에 계산한다.
5. 실행 베이스는 `60m`로 유지하고, 더 짧은 봉은 내부 확인 신호로만 사용한다.
6. 연구 목적함수는 `full-period excess return`을 최우선으로 하고, `full-period MDD <= 20%`를 하드 컷으로 둔다.

**State Machine**

- `full_long`
  - 매크로 점수가 강세 기준 이상
  - 마이크로 점수도 강세 기준 이상
  - 목표 비중은 `FULL_LONG_PCT`
- `reduced`
  - 매크로는 강세 또는 중립이지만 마이크로 확인이 약한 경우
  - 또는 매크로는 중립이지만 마이크로가 충분히 강한 경우
  - 목표 비중은 `REDUCED_PCT`
- `flat`
  - 매크로 점수가 약세이거나
  - 장기 고점 대비 낙폭이 허용 한도를 넘는 경우
  - 목표 비중은 `0`

**Signals**

- 매크로 점수
  - `close > SMA(window)`
  - `SMA(window)` 상승 여부
  - 최근 장기 고점 대비 낙폭
- 마이크로 점수
  - `EMA fast > EMA slow` 정렬
  - 단기 breakout 회복
  - 단기 momentum 양수 여부

**Research Objective**

- 하드 컷:
  - `full_period.max_drawdown_pct > 20`
- 랭킹:
  - `full_period_excess_return = strategy_return - buy_hold_return`
  - `test_excess_return` 가산
  - 과도한 거래 수는 패널티

**Search Scope**

- `FULL_LONG_PCT`
- `REDUCED_PCT`
- `MACRO_FULL_THRESHOLD`
- `MACRO_REDUCED_THRESHOLD`
- `MICRO_FULL_THRESHOLD`
- `MICRO_REDUCED_THRESHOLD`
- `MAX_MACRO_DRAWDOWN`

탐색은 1차 라운드에서 작은 그리드만 사용한다. 목표는 완전한 최적화가 아니라, 기존 60분봉 전략보다 장기 수익 회복 가능성이 있는 구조적 후보를 찾는 것이다.
