"""기본 에이전트 인터페이스."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentResponse:
    agent_name: str
    coin_id: str
    signal: str          # "bullish" | "bearish" | "neutral"
    confidence: float    # 0.0 ~ 1.0
    reasoning: str
    raw_data: dict[str, Any]


class BaseAgent:
    """모든 분석가 에이전트의 기본 클래스."""

    name: str = "base"

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.model = os.environ.get("OPENAI_DEFAULT_MODEL", "gpt-4o")
        self.reasoning_effort = os.environ.get("OPENAI_REASONING_EFFORT", "high")

        if not self.api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY 환경변수가 설정되지 않았습니다. "
                "research/tradingagents/.env.example을 참고하세요."
            )

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """OpenAI Responses API 호출."""
        import requests  # stdlib requests 사용

        resp = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "reasoning": {"effort": self.reasoning_effort},
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["output"][0]["content"][0]["text"]

    def analyze(self, coin: dict) -> AgentResponse:
        """서브클래스에서 구현. coin = {"id", "symbol", "name", ...}"""
        raise NotImplementedError
