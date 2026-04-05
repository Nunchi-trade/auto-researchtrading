"""
TradingAgents — 4개 분석가 에이전트 파이프라인.

에이전트 구조:
  FundamentalsAgent  → 온체인 지표, 토크노믹스, 개발 활동
  SentimentAgent     → 소셜 미디어, Fear & Greed Index
  NewsAgent          → 주요 뉴스 이벤트, 규제 이슈
  TechnicalAgent     → 가격/거래량 기술적 지표

토론:
  BullDebater  → 매수 논거 제시
  BearDebater  → 매도 논거 제시

최종 결정:
  RiskManager  → 토론 결과 + 포트폴리오 리스크 → 최종 포지션 방향
"""
from .base import BaseAgent, AgentResponse
from .fundamentals import FundamentalsAgent
from .sentiment import SentimentAgent
from .news import NewsAgent
from .technical import TechnicalAgent
from .debate import BullDebater, BearDebater
from .risk import RiskManager

__all__ = [
    "BaseAgent",
    "AgentResponse",
    "FundamentalsAgent",
    "SentimentAgent",
    "NewsAgent",
    "TechnicalAgent",
    "BullDebater",
    "BearDebater",
    "RiskManager",
]
