# Upbit Asymmetric Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 강한 추세에서만 포지션 크기를 비대칭적으로 키워 수익을 개선하되 기존 drawdown 통제를 유지한다.

**Architecture:** 전략에는 세 개의 boost 파라미터만 추가로 오버라이드 가능하게 만든다. 기본값은 boost를 비활성화한 상태로 두고, 연구는 작은 커스텀 그리드와 기존 `return_risk` 목적함수로만 수행한다.

**Tech Stack:** Python 3.10+, numpy, pandas, uv, pytest

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `upbit_strategy.py` | strong trend boost 파라미터 추가 |
| `tests/test_upbit_strategy.py` | boost 회귀 테스트 |

### Task 1: 실패 테스트 추가

**Files:**
- Modify: `tests/test_upbit_strategy.py`

- [ ] strong trend boost가 entry target을 키우는 실패 테스트 작성
- [ ] 새 테스트 실행 → 실패 확인

### Task 2: 최소 구현

**Files:**
- Modify: `upbit_strategy.py`

- [ ] boost 기본값과 오버라이드 추가
- [ ] 진입 시 strong trend 조건에서만 boost 적용
- [ ] 새 테스트 재실행

### Task 3: 자동화 연구

**Files:**
- Modify: `upbit_strategy.py` (최종 조합 반영 시에만)

- [ ] 240분봉 coarse shortlist 실행
- [ ] 상위 3개를 60분봉 full check
- [ ] 최상위 조합만 기본값 반영 여부 결정
- [ ] 전체 테스트와 split 재검증
