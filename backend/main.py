from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.routes import dashboard, live, params, strategies

app = FastAPI(
    title="AutoTrader Dashboard API",
    version="0.1.0",
    description="Backend for Upbit research & live monitoring dashboard.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(strategies.router)
app.include_router(params.router)
app.include_router(live.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


DESIGNS_DIR = Path(__file__).resolve().parent.parent / ".stitch" / "designs"
if DESIGNS_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(DESIGNS_DIR), html=True), name="ui")
