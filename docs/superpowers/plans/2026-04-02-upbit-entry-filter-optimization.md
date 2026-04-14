# Upbit Entry Filter Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 진입/추세 필터를 재조정해 수익을 끌어올리되 현재 수준의 drawdown 통제를 유지한다.

**Architecture:** 전략에는 세 개의 진입 파라미터만 추가로 오버라이드 가능하게 만든다. 연구 파이프라인은 기존 `return_risk` 목적함수를 재사용하고, 이번 라운드는 작은 커스텀 그리드로만 탐색한다. 기본값 변경은 60분봉 full check를 통과한 조합이 있을 때만 수행한다.

**Tech Stack:** Python 3.10+, numpy, pandas, uv, pytest

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `upbit_strategy.py` | trend/adx 진입 파라미터 추가 |
| `tests/test_upbit_strategy.py` | 새 진입 파라미터 회귀 테스트 |

### Task 1: 실패 테스트 추가

**Files:**
- Modify: `tests/test_upbit_strategy.py`

- [ ] `ADX_ENTRY_THRESHOLD`가 진입 여부를 바꾸는 실패 테스트 작성
- [ ] `TREND_FILTER_BARS` 또는 `SMA_SLOPE_THRESHOLD`가 진입 여부를 바꾸는 실패 테스트 작성
- [ ] 새 테스트 실행 → 실패 확인

### Task 2: 최소 구현

**Files:**
- Modify: `upbit_strategy.py`

- [ ] 세 파라미터를 기본값/오버라이드 dict에 추가
- [ ] 진입 로직에서 파라미터 사용
- [ ] 새 테스트 재실행

### Task 3: 자동화 연구

**Files:**
- Modify: `upbit_strategy.py` (최종 조합 반영 시에만)

- [ ] 240분봉 coarse shortlist 실행
- [ ] 상위 3개를 60분봉 full check
- [ ] 최상위 조합만 기본값 반영 여부 결정
- [ ] 전체 테스트와 60분봉 split 재검증
