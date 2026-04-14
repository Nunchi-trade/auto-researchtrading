# Upbit Balanced Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `train/val/test`를 동시에 고려하는 목적함수와 자동 탐색 스크립트를 추가해 Upbit 전략의 균형 성능을 개선한다.

**Architecture:** 전략 파일은 탐색 대상 파라미터만 오버라이드 가능하게 최소 수정한다. 평가/탐색 로직은 별도 모듈로 분리하고, 스크립트는 CLI 출력만 담당한다. 최종 기본값 변경은 탐색 결과 상위 1개 조합에 한정한다.

**Tech Stack:** Python 3.10+, numpy, pandas, uv, pytest

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `upbit_strategy.py` | 탐색 대상 파라미터 오버라이드 지원 |
| `upbit_balanced_research.py` | 균형 목적함수 + 그리드 생성 + 조합 평가 |
| `scripts/upbit_balanced_search.py` | CLI 진입점 |
| `tests/test_upbit_strategy.py` | 전략 파라미터 오버라이드 검증 |
| `tests/test_upbit_balanced_research.py` | 균형 목적함수/그리드 테스트 |

### Task 1: 실패 테스트 추가

**Files:**
- Modify: `tests/test_upbit_strategy.py`
- Create: `tests/test_upbit_balanced_research.py`

- [ ] 파라미터 오버라이드가 실제 target position에 반영되는 테스트 작성
- [ ] 균형 목적함수가 편차 큰 조합보다 고른 조합을 더 높게 평가하는 테스트 작성
- [ ] 새 테스트를 실행해 실패 확인

### Task 2: 최소 구현

**Files:**
- Modify: `upbit_strategy.py`
- Create: `upbit_balanced_research.py`
- Create: `scripts/upbit_balanced_search.py`

- [ ] 전략 기본 파라미터 dict와 오버라이드 병합 로직 추가
- [ ] 균형 목적함수와 조합 평가 함수 구현
- [ ] CLI 스크립트 추가
- [ ] 테스트 재실행

### Task 3: 자동 탐색 실행 및 반영

**Files:**
- Modify: `upbit_strategy.py` (최상위 조합 반영 시에만)

- [ ] 자동 탐색 스크립트 실행
- [ ] 상위 조합 비교
- [ ] 기본값 반영 여부 결정
- [ ] 전체 테스트와 `train/val/test` 백테스트 재검증
