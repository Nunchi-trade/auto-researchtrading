"""불/베어 토론 에이전트 — 4개 분석 결과를 바탕으로 토론."""
from __future__ import annotations

import json
from .base import BaseAgent, AgentResponse

BULL_PROMPT = """당신은 크립토 투자의 낙관론자입니다.
주어진 분석 데이터를 바탕으로 가장 강력한 매수 논거를 제시하세요.
반드시 JSON으로만 응답하세요: {"signal": "bullish", "confidence": 0.0~1.0, "reasoning": "..."}"""

BEAR_PROMPT = """당신은 크립토 투자의 비관론자입니다.
주어진 분석 데이터를 바탕으로 가장 강력한 매도/리스크 논거를 제시하세요.
반드시 JSON으로만 응답하세요: {"signal": "bearish", "confidence": 0.0~1.0, "reasoning": "..."}"""


def _format_analyses(analyses: list[AgentResponse]) -> str:
    lines = []
    for a in analyses:
        lines.append(f"[{a.agent_name}] {a.signal} (신뢰도 {a.confidence:.0%}): {a.reasoning[:200]}")
    return "\n".join(lines)


class BullDebater(BaseAgent):
    name = "bull_debater"

    def analyze_with_context(self, coin: dict, analyses: list[AgentResponse]) -> AgentResponse:
        context = f"코인: {coin['name']} ({coin['symbol']})\n\n분석 결과:\n{_format_analyses(analyses)}"
        raw_response = self._call_llm(BULL_PROMPT, context)
        try:
            result = json.loads(raw_response)
        except json.JSONDecodeError:
            result = {"signal": "bullish", "confidence": 0.5, "reasoning": raw_response}

        return AgentResponse(
            agent_name=self.name, coin_id=coin["id"],
            signal="bullish",
            confidence=float(result.get("confidence", 0.5)),
            reasoning=result.get("reasoning", ""),
            raw_data={},
        )

    def analyze(self, coin: dict) -> AgentResponse:
        return self.analyze_with_context(coin, [])


class BearDebater(BaseAgent):
    name = "bear_debater"

    def analyze_with_context(self, coin: dict, analyses: list[AgentResponse]) -> AgentResponse:
        context = f"코인: {coin['name']} ({coin['symbol']})\n\n분석 결과:\n{_format_analyses(analyses)}"
        raw_response = self._call_llm(BEAR_PROMPT, context)
        try:
            result = json.loads(raw_response)
        except json.JSONDecodeError:
            result = {"signal": "bearish", "confidence": 0.5, "reasoning": raw_response}

        return AgentResponse(
            agent_name=self.name, coin_id=coin["id"],
            signal="bearish",
            confidence=float(result.get("confidence", 0.5)),
            reasoning=result.get("reasoning", ""),
            raw_data={},
        )

    def analyze(self, coin: dict) -> AgentResponse:
        return self.analyze_with_context(coin, [])
