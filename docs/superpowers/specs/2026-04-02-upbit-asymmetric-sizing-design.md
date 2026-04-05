# Upbit Asymmetric Sizing Design

**Context**

출구 민감도 조정과 진입 필터 조정은 모두 현재 기본값을 이기지 못했다. 병목은 신호 품질 자체보다, 강한 추세 구간에서도 포지션이 동일한 크기로만 들어간다는 점일 가능성이 크다.

**Goal**

평범한 구간의 리스크는 유지하면서, 강한 추세 구간에서만 포지션을 비대칭적으로 키워 수익을 더 끌어올린다.

**Design**

1. 전략에 강한 추세 전용 사이징 배수 3개를 추가한다.
   - `TREND_BOOST_MAX`
   - `ADX_BOOST_THRESHOLD`
   - `SLOPE_BOOST_THRESHOLD`
2. 기본값은 `TREND_BOOST_MAX=1.0`으로 둬 현재 전략 동작을 유지한다.
3. 진입 시 `ADX`, `SMA slope`, `aux_bull`이 모두 충분히 강할 때만 추가 배수를 곱한다.
4. 목적함수는 기존 `return_risk`를 유지하고, drawdown이 현재 수준보다 크게 나빠지면 탈락시킨다.

**Search Scope**

- `TREND_BOOST_MAX`: `1.00`, `1.15`, `1.30`
- `ADX_BOOST_THRESHOLD`: `22`, `26`
- `SLOPE_BOOST_THRESHOLD`: `0.0025`, `0.0035`

**Success Criteria**

- 강한 추세에서만 entry target이 커지는 테스트가 추가된다.
- 240분봉 coarse shortlist와 60분봉 full check를 거쳐 기본값 교체 여부를 결정한다.
- drawdown이 크게 악화되지 않는 한도에서 수익 또는 `return_risk`가 개선되면 기본값을 교체한다.
