from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from backend.models import ParamCandidate, ParamSearchRun
from upbit_mtf_research import load_search_results

router = APIRouter(prefix="/api/params", tags=["params"])

RESULTS_DIR = (Path.home() / ".cache" / "autotrader_upbit").resolve()
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+\.jsonl$")


def _find_run_file(run_id: str) -> Path:
    if not SAFE_RUN_ID.match(run_id):
        raise HTTPException(status_code=400, detail="invalid run_id format")
    candidate = (RESULTS_DIR / run_id).resolve()
    if not candidate.is_relative_to(RESULTS_DIR):
        raise HTTPException(status_code=400, detail="run_id escapes results dir")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"search run not found: {run_id}")
    return candidate


def _scan_jsonl_summary(path: Path) -> tuple[int, float]:
    """Stream JSONL once: return (line_count, best_objective_score)."""
    import json as _json
    count = 0
    best = float("-inf")
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            count += 1
            try:
                row = _json.loads(line)
            except Exception:
                continue
            score = row.get("objective_score")
            if isinstance(score, (int, float)) and score > best:
                best = score
    return count, (0.0 if best == float("-inf") else best)


@router.get("/searches", response_model=list[ParamSearchRun])
def list_searches():
    out: list[ParamSearchRun] = []
    for path in sorted(RESULTS_DIR.glob("*.jsonl")):
        try:
            count, best = _scan_jsonl_summary(path)
        except Exception:
            continue
        out.append(ParamSearchRun(
            run_id=path.name,
            path=str(path),
            num_candidates=count,
            best_objective=float(best),
            updated_ts=int(path.stat().st_mtime),
        ))
    return out


@router.get("/searches/{run_id}/top", response_model=list[ParamCandidate])
def top_candidates(run_id: str, limit: int = Query(10, ge=1, le=100)):
    rows = load_search_results(_find_run_file(run_id))
    ranked = sorted(rows, key=lambda r: r.get("objective_score", float("-inf")), reverse=True)
    out: list[ParamCandidate] = []
    for rank, row in enumerate(ranked[:limit], start=1):
        metrics = row.get("metrics") or {}
        full = metrics.get("full") or {}
        test = metrics.get("test") or {}
        out.append(ParamCandidate(
            rank=rank,
            objective_score=float(row.get("objective_score", 0.0)),
            params=row.get("params", {}),
            full_excess_return_pct=float(full.get("excess_return_pct", 0.0)),
            test_excess_return_pct=float(test.get("excess_return_pct", 0.0)),
            max_drawdown_pct=float(full.get("drawdown_pct", 0.0)),
            num_trades=int(full.get("trades", 0)),
        ))
    return out


@router.get("/searches/{run_id}/heatmap")
def heatmap(run_id: str, x_param: str = "MAX_MACRO_DRAWDOWN", y_param: str = "STATE_CONFIRM_BARS"):
    rows = load_search_results(_find_run_file(run_id))
    cells: dict[tuple, float] = {}
    for row in rows:
        params = row.get("params") or {}
        x = params.get(x_param)
        y = params.get(y_param)
        if x is None or y is None:
            continue
        score = row.get("objective_score", float("-inf"))
        key = (float(x), float(y))
        cells[key] = max(cells.get(key, float("-inf")), float(score))
    return {
        "x_param": x_param,
        "y_param": y_param,
        "cells": [{"x": x, "y": y, "score": s} for (x, y), s in cells.items()],
    }
