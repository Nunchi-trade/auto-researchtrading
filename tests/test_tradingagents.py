"""TradingAgents 파이프라인 유닛 테스트 (LLM/API 목 처리)."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research", "tradingagents"))


# ---------------------------------------------------------------------------
# fetch_top300 테스트
# ---------------------------------------------------------------------------

def _make_coin_response(coin_id: str, symbol: str, name: str, is_stable: bool = False) -> dict:
    return {
        "id": coin_id,
        "symbol": symbol,
        "name": name,
        "market_cap": 1_000_000_000,
        "current_price": 100.0,
    }


def test_fetch_top_altcoins_excludes_stablecoins():
    """스테이블코인은 결과에서 제외된다."""
    from fetch_top300 import fetch_top_altcoins, STABLECOIN_IDS

    fake_coins = [
        {"id": "solana", "symbol": "sol", "name": "Solana",
         "market_cap": 50_000_000_000, "current_price": 100.0},
        {"id": "tether", "symbol": "usdt", "name": "Tether",
         "market_cap": 100_000_000_000, "current_price": 1.0},
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin",
         "market_cap": 900_000_000_000, "current_price": 50000.0},
    ]

    mock_resp = MagicMock()
    mock_resp.json.side_effect = [fake_coins, []]
    mock_resp.raise_for_status.return_value = None

    with patch("fetch_top300.requests.get", return_value=mock_resp):
        result = fetch_top_altcoins(10)

    ids = [c["id"] for c in result]
    assert "tether" not in ids, "스테이블코인이 결과에 포함됨"
    assert "bitcoin" not in ids, "BTC가 결과에 포함됨"
    assert "solana" in ids, "SOL이 결과에 없음"


def test_fetch_top_altcoins_returns_required_fields():
    """반환 딕셔너리에 필수 필드가 있다."""
    from fetch_top300 import fetch_top_altcoins
    fake_coins = [
        {"id": "cardano", "symbol": "ada", "name": "Cardano",
         "market_cap": 10_000_000_000, "current_price": 0.5},
    ]
    mock_resp = MagicMock()
    mock_resp.json.side_effect = [fake_coins, []]
    mock_resp.raise_for_status.return_value = None

    with patch("fetch_top300.requests.get", return_value=mock_resp):
        result = fetch_top_altcoins(5)

    assert len(result) == 1
    coin = result[0]
    for field in ("id", "symbol", "name", "market_cap", "current_price"):
        assert field in coin, f"필수 필드 없음: {field}"


# ---------------------------------------------------------------------------
# BaseAgent 테스트
# ---------------------------------------------------------------------------

def test_base_agent_raises_without_api_key():
    """OPENAI_API_KEY 없으면 초기화 시 EnvironmentError."""
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("OPENAI_API_KEY", None)
        from agents.base import BaseAgent

        class _ConcreteAgent(BaseAgent):
            name = "test"
            def analyze(self, coin):
                pass

        with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
            _ConcreteAgent()


def test_agent_response_dataclass_fields():
    """AgentResponse 데이터클래스가 필수 필드를 가진다."""
    from agents.base import AgentResponse
    resp = AgentResponse(
        agent_name="test",
        coin_id="solana",
        signal="bullish",
        confidence=0.8,
        reasoning="강한 추세",
        raw_data={"key": "value"},
    )
    assert resp.signal == "bullish"
    assert resp.confidence == 0.8
    assert resp.agent_name == "test"


# ---------------------------------------------------------------------------
# RiskManager 테스트
# ---------------------------------------------------------------------------

def test_risk_manager_decide_returns_agent_response():
    """RiskManager.decide()가 AgentResponse를 반환한다."""
    from agents.base import AgentResponse
    from agents.risk import RiskManager

    coin = {"id": "solana", "symbol": "SOL", "name": "Solana"}
    bull = AgentResponse("bull", "solana", "bullish", 0.8, "상승 추세", {})
    bear = AgentResponse("bear", "solana", "bearish", 0.4, "리스크 존재", {})
    analysts = [
        AgentResponse("fundamentals", "solana", "bullish", 0.7, "강한 펀더멘털", {}),
        AgentResponse("technical", "solana", "bullish", 0.75, "기술적 강세", {}),
    ]

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        manager = RiskManager()

    mock_llm_response = '{"signal": "buy", "position_pct": 0.05, "confidence": 0.75, "reasoning": "긍정적 신호 우세"}'
    with patch.object(manager, "_call_llm", return_value=mock_llm_response):
        result = manager.decide(coin, analysts, bull, bear)

    assert isinstance(result, AgentResponse)
    assert result.signal in ("strong_buy", "buy", "hold", "sell", "strong_sell")
    assert 0.0 <= result.confidence <= 1.0
