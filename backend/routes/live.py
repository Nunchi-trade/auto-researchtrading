from __future__ import annotations

import time

from fastapi import APIRouter

from backend.models import LiveOrder, LivePosition, LiveSnapshot

router = APIRouter(prefix="/api/live", tags=["live"])


def _mock_ticker() -> dict:
    return {
        "symbol": "KRW-BTC",
        "price": 142_350_000.0,
        "change_pct_24h": 2.34,
        "open_24h": 139_120_000.0,
        "high_24h": 143_800_000.0,
        "low_24h": 138_900_000.0,
        "volume_24h_krw": 284_500_000_000.0,
    }


def _mock_position() -> LivePosition:
    return LivePosition(
        strategy="mtf",
        state="full_long",
        symbol="KRW-BTC",
        size_krw=48_619_424.0,
        size_coin=0.3421,
        avg_entry_price=141_200_000.0,
        current_price=142_350_000.0,
        unrealized_pnl_krw=395_240.0,
        unrealized_pnl_pct=0.81,
        time_in_position_seconds=16_320,
    )


def _mock_orders() -> list[LiveOrder]:
    now = int(time.time())
    return [
        LiveOrder(timestamp=now - 600, action="buy", symbol="KRW-BTC",
                  size_coin=0.0834, price=141_200_000.0, fee_krw=42_840.0, status="filled"),
        LiveOrder(timestamp=now - 2400, action="buy", symbol="KRW-BTC",
                  size_coin=0.0412, price=141_050_000.0, fee_krw=21_120.0, status="filled"),
        LiveOrder(timestamp=now - 2401, action="buy", symbol="KRW-BTC",
                  size_coin=0.0088, price=141_080_000.0, fee_krw=4_521.0, status="partial"),
        LiveOrder(timestamp=now - 4200, action="sell", symbol="KRW-BTC",
                  size_coin=0.0521, price=138_500_000.0, fee_krw=26_720.0, status="filled"),
    ]


@router.get("/snapshot", response_model=LiveSnapshot)
def get_snapshot():
    return LiveSnapshot(
        ticker=_mock_ticker(),
        position=_mock_position(),
        recent_orders=_mock_orders(),
        system_status={
            "api": "ok",
            "websocket": "ok",
            "strategy_engine": "ok",
            "data_pipeline": "ok",
            "last_error": "none",
        },
    )


@router.get("/ticker")
def get_ticker():
    return _mock_ticker()


@router.get("/position", response_model=LivePosition)
def get_position():
    return _mock_position()


@router.get("/orders", response_model=list[LiveOrder])
def get_orders():
    return _mock_orders()
