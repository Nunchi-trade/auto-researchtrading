"""기술적 분석 에이전트 — yfinance OHLCV 기반."""
from __future__ import annotations

import json
import requests
from .base import BaseAgent, AgentResponse

SYSTEM_PROMPT = """당신은 크립토 기술적 분석 전문가입니다.
가격 추세, 이동평균, RSI, MACD, 볼린저밴드를 분석합니다.
반드시 JSON으로만 응답하세요: {"signal": "bullish"|"bearish"|"neutral", "confidence": 0.0~1.0, "reasoning": "..."}"""

COINGECKO_URL = "https://api.coingecko.com/api/v3"


def _fetch_ohlcv(coin_id: str, days: int = 30) -> list[list]:
    """CoinGecko OHLCV (days일치, USD)."""
    import os
    api_key = os.getenv("COINGECKO_API_KEY", "")
    headers = {"x-cg-demo-api-key": api_key} if api_key else {}
    try:
        resp = requests.get(
            f"{COINGECKO_URL}/coins/{coin_id}/ohlc",
            headers=headers,
            params={"vs_currency": "usd", "days": days},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


class TechnicalAgent(BaseAgent):
    name = "technical"

    def analyze(self, coin: dict) -> AgentResponse:
        ohlcv = _fetch_ohlcv(coin["id"], days=30)

        if len(ohlcv) < 10:
            return AgentResponse(
                agent_name=self.name, coin_id=coin["id"],
                signal="neutral", confidence=0.3,
                reasoning="데이터 부족",
                raw_data={},
            )

        closes = [row[4] for row in ohlcv]
        recent = closes[-7:]
        trend = (recent[-1] - recent[0]) / recent[0] * 100

        summary = (
            f"코인: {coin['name']} ({coin['symbol']})\n"
            f"현재가: ${closes[-1]:,.2f}\n"
            f"7일 수익률: {trend:+.2f}%\n"
            f"30일 고가: ${max(closes):,.2f}\n"
            f"30일 저가: ${min(closes):,.2f}\n"
        )

        raw_response = self._call_llm(SYSTEM_PROMPT, summary)
        try:
            result = json.loads(raw_response)
        except json.JSONDecodeError:
            result = {"signal": "neutral", "confidence": 0.5, "reasoning": raw_response}

        return AgentResponse(
            agent_name=self.name,
            coin_id=coin["id"],
            signal=result.get("signal", "neutral"),
            confidence=float(result.get("confidence", 0.5)),
            reasoning=result.get("reasoning", ""),
            raw_data={"close_7d_trend": trend},
        )
