"""감성 분석 에이전트 — Fear & Greed Index, 소셜 지표."""
from __future__ import annotations

import json
import requests
from .base import BaseAgent, AgentResponse

SYSTEM_PROMPT = """당신은 크립토 시장 감성 분석 전문가입니다.
Fear & Greed Index, 소셜 미디어 활동, 커뮤니티 성장을 분석합니다.
반드시 JSON으로만 응답하세요: {"signal": "bullish"|"bearish"|"neutral", "confidence": 0.0~1.0, "reasoning": "..."}"""


def _fetch_fear_greed() -> dict:
    """Alternative.me Fear & Greed Index."""
    try:
        resp = requests.get("https://api.alternative.me/fng/?limit=7", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


class SentimentAgent(BaseAgent):
    name = "sentiment"

    def analyze(self, coin: dict) -> AgentResponse:
        fng_data = _fetch_fear_greed()
        fng_list = fng_data.get("data", [])
        current_fng = fng_list[0] if fng_list else {}

        summary = (
            f"코인: {coin['name']} ({coin['symbol']})\n"
            f"현재 Fear & Greed: {current_fng.get('value', 'N/A')} ({current_fng.get('value_classification', 'N/A')})\n"
            f"7일 평균 Fear & Greed: {sum(int(x.get('value', 50)) for x in fng_list) / max(len(fng_list), 1):.1f}\n"
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
            raw_data={"fear_greed": current_fng},
        )
