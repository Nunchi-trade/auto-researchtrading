"""리스크 매니저 — 토론 결과를 종합해 최종 포지션 결정."""
from __future__ import annotations

import json
from .base import BaseAgent, AgentResponse

SYSTEM_PROMPT = """당신은 크립토 포트폴리오 리스크 매니저입니다.
불/베어 토론 결과와 시장 분석을 종합하여 최종 포지션 방향과 크기를 결정합니다.
반드시 JSON으로만 응답하세요:
{
  "signal": "strong_buy"|"buy"|"hold"|"sell"|"strong_sell",
  "position_pct": 0.0~1.0,  // 포트폴리오 대비 포지션 비율
  "confidence": 0.0~1.0,
  "reasoning": "..."
}"""


class RiskManager(BaseAgent):
    name = "risk_manager"

    def decide(
        self,
        coin: dict,
        analyst_responses: list[AgentResponse],
        bull_response: AgentResponse,
        bear_response: AgentResponse,
    ) -> AgentResponse:
        bull_strength = bull_response.confidence
        bear_strength = bear_response.confidence

        analyst_summary = "\n".join(
            f"[{a.agent_name}] {a.signal} (신뢰도 {a.confidence:.0%})" for a in analyst_responses
        )
        debate_summary = (
            f"[불 논거 ({bull_strength:.0%} 신뢰)] {bull_response.reasoning[:300]}\n"
            f"[베어 논거 ({bear_strength:.0%} 신뢰)] {bear_response.reasoning[:300]}"
        )

        context = (
            f"코인: {coin['name']} ({coin['symbol']})\n\n"
            f"분석가 결과:\n{analyst_summary}\n\n"
            f"토론:\n{debate_summary}"
        )

        raw_response = self._call_llm(SYSTEM_PROMPT, context)
        try:
            result = json.loads(raw_response)
        except json.JSONDecodeError:
            result = {"signal": "hold", "position_pct": 0.0, "confidence": 0.3, "reasoning": raw_response}

        return AgentResponse(
            agent_name=self.name,
            coin_id=coin["id"],
            signal=result.get("signal", "hold"),
            confidence=float(result.get("confidence", 0.3)),
            reasoning=result.get("reasoning", ""),
            raw_data={"position_pct": result.get("position_pct", 0.0)},
        )

    def analyze(self, coin: dict) -> AgentResponse:
        return AgentResponse(
            agent_name=self.name, coin_id=coin["id"],
            signal="hold", confidence=0.0,
            reasoning="decide() 메서드로 직접 호출하세요",
            raw_data={},
        )
