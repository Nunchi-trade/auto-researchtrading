"""펀더멘털 분석 에이전트 — CoinGecko 온체인/토크노믹스 데이터."""
from __future__ import annotations

import os
import requests
from .base import BaseAgent, AgentResponse

COINGECKO_URL = "https://api.coingecko.com/api/v3"

SYSTEM_PROMPT = """당신은 크립토 펀더멘털 분석 전문가입니다.
토크노믹스, 온체인 지표, 개발 활동, 팀/생태계를 분석하여 투자 신호를 제공합니다.
반드시 JSON으로만 응답하세요: {"signal": "bullish"|"bearish"|"neutral", "confidence": 0.0~1.0, "reasoning": "..."}"""


class FundamentalsAgent(BaseAgent):
    name = "fundamentals"

    def _fetch_coin_data(self, coin_id: str) -> dict:
        api_key = os.getenv("COINGECKO_API_KEY", "")
        headers = {"x-cg-demo-api-key": api_key} if api_key else {}
        resp = requests.get(
            f"{COINGECKO_URL}/coins/{coin_id}",
            headers=headers,
            params={"localization": False, "tickers": False,
                    "market_data": True, "community_data": True,
                    "developer_data": True},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def analyze(self, coin: dict) -> AgentResponse:
        raw = self._fetch_coin_data(coin["id"])
        market = raw.get("market_data", {})
        dev = raw.get("developer_data", {})
        community = raw.get("community_data", {})

        summary = (
            f"코인: {coin['name']} ({coin['symbol']})\n"
            f"시가총액 순위: #{raw.get('market_cap_rank', 'N/A')}\n"
            f"24h 거래량/시가총액: {market.get('total_volume', {}).get('usd', 0) / max(market.get('market_cap', {}).get('usd', 1), 1):.3f}\n"
            f"GitHub Stars: {dev.get('stars', 0)}, Commits(4주): {dev.get('commit_count_4_weeks', 0)}\n"
            f"Twitter 팔로워: {community.get('twitter_followers', 0):,}\n"
            f"유통 공급량/최대 공급량: {market.get('circulating_supply', 0)} / {market.get('max_supply') or '무제한'}\n"
        )

        import json
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
            raw_data={"coingecko_summary": summary},
        )
