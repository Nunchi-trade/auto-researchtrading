# Upbit MTF State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 다중 타임프레임 기반 `flat / reduced / full_long` 전략을 새로 추가하고, 전체 기간 초과수익을 기준으로 자동화 탐색까지 수행한다.

**Architecture:** 전략은 별도 `upbit_mtf_strategy.py`에서 상태기계와 MTF feature lookup을 담당한다. 연구 모듈 `upbit_mtf_research.py`는 전체 기간 데이터 로드, buy-and-hold 벤치마크 계산, 목적함수 평가, 그리드 탐색을 담당한다. 기존 전략 파일은 비교 기준으로 유지한다.

**Tech Stack:** Python 3.10+, numpy, pandas, uv, pytest

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `upbit_mtf_strategy.py` | MTF 상태기계 전략 + feature store |
| `upbit_mtf_research.py` | full-period excess return 평가 + 검색 유틸 |
| `scripts/upbit_mtf_search.py` | 자동화 탐색 CLI |
| `tests/test_upbit_mtf_strategy.py` | 상태기계 진입/감산/청산 테스트 |
| `tests/test_upbit_mtf_research.py` | 목적함수 및 검색 결과 정렬 테스트 |

### Task 1: 실패 테스트 추가

**Files:**
- Create: `tests/test_upbit_mtf_strategy.py`
- Create: `tests/test_upbit_mtf_research.py`

- [ ] `full_long`, `reduced`, `flat` 상태를 검증하는 실패 테스트 작성
- [ ] full-period excess return 목적함수 하드 컷과 선호도를 검증하는 실패 테스트 작성
- [ ] 새 테스트를 실행해 실패 확인

### Task 2: 최소 구현

**Files:**
- Create: `upbit_mtf_strategy.py`
- Create: `upbit_mtf_research.py`
- Create: `scripts/upbit_mtf_search.py`

- [ ] 상태기계 전략 구현
- [ ] 전체 기간 데이터 로더와 목적함수 구현
- [ ] 검색 CLI 구현
- [ ] 테스트 재실행

### Task 3: 자동화 탐색 및 결과 반영

**Files:**
- Modify: `upbit_mtf_strategy.py` (최종 기본값 갱신 시)

- [ ] 전체 기간 기준 small-grid 탐색 실행
- [ ] 상위 후보를 재평가해 기본값 확정
- [ ] 전체 테스트 실행
- [ ] 수익률, buy-and-hold 초과수익, MDD 결과를 정리
