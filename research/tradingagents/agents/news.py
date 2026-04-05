"""뉴스 분석 에이전트 — CoinGecko 최근 이벤트."""
from __future__ import annotations

import json
import os
import requests
from .base import BaseAgent, AgentResponse

COINGECKO_URL = "https://api.coingecko.com/api/v3"

SYSTEM_PROMPT = """당신은 크립토 뉴스 분석 전문가입니다.
최근 이벤트, 규제 이슈, 파트너십, 기술 업그레이드를 분석합니다.
반드시 JSON으로만 응답하세요: {"signal": "bullish"|"bearish"|"neutral", "confidence": 0.0~1.0, "reasoning": "..."}"""


class NewsAgent(BaseAgent):
    name = "news"

    def _fetch_events(self, coin_id: str) -> list[dict]:
        api_key = os.getenv("COINGECKO_API_KEY", "")
        headers = {"x-cg-demo-api-key": api_key} if api_key else {}
        try:
            resp = requests.get(
                f"{COINGECKO_URL}/events",
                headers=headers,
                params={"country_code": "US", "page": 1},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("data", [])[:10]
        except Exception:
            return []

    def analyze(self, coin: dict) -> AgentResponse:
        events = self._fetch_events(coin["id"])

        if events:
            event_text = "\n".join(
                f"- {e.get('title', '')} ({e.get('start_date', '')})" for e in events
            )
        else:
            event_text = "최근 주요 이벤트 없음"

        summary = f"코인: {coin['name']} ({coin['symbol']})\n최근 이벤트:\n{event_text}"

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
            raw_data={"events_count": len(events)},
        )
