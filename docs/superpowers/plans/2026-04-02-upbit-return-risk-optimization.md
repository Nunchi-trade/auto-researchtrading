# Upbit Return/Risk Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수익을 더 끌어올리면서 각 split의 drawdown을 낮게 유지하는 방향으로 Upbit 전략 출구 민감도를 재조정한다.

**Architecture:** 전략은 두 개의 출구 파라미터만 추가로 오버라이드 가능하게 바꾼다. 연구 모듈은 기존 balanced 목적함수와 별개로 return/risk 목적함수를 제공하고, 스크립트는 어떤 목적함수를 쓸지 선택만 받는다. 탐색 결과 반영은 최종 상위 1개 조합에 한정한다.

**Tech Stack:** Python 3.10+, numpy, pandas, uv, pytest

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `upbit_strategy.py` | 출구 민감도 파라미터 추가 |
| `upbit_balanced_research.py` | return/risk 목적함수 + 목적함수 선택 지원 |
| `scripts/upbit_balanced_search.py` | 목적함수 선택 CLI |
| `tests/test_upbit_strategy.py` | 새 출구 파라미터 동작 테스트 |
| `tests/test_upbit_balanced_research.py` | return/risk 목적함수 테스트 |

### Task 1: 실패 테스트 추가

**Files:**
- Modify: `tests/test_upbit_strategy.py`
- Modify: `tests/test_upbit_balanced_research.py`

- [ ] `RECENT_HIGH_BUFFER`가 exit 판단을 바꾸는 실패 테스트 작성
- [ ] return/risk 목적함수 하드 컷 및 선호도를 검증하는 실패 테스트 작성
- [ ] 새 테스트를 실행해 실패 확인

### Task 2: 최소 구현

**Files:**
- Modify: `upbit_strategy.py`
- Modify: `upbit_balanced_research.py`
- Modify: `scripts/upbit_balanced_search.py`

- [ ] 출구 파라미터 오버라이드 추가
- [ ] return/risk 목적함수 구현
- [ ] 스크립트 objective 선택 지원
- [ ] 테스트 재실행

### Task 3: 후보 평가 및 반영

**Files:**
- Modify: `upbit_strategy.py` (최종 조합 반영 시에만)

- [ ] 240분봉 coarse shortlist 실행
- [ ] 상위 3개를 60분봉 full check
- [ ] 최상위 1개만 기본값 반영
- [ ] 전체 테스트와 split 재검증
