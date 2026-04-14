"""
TradingAgents 메인 파이프라인.

사용법:
    cp .env.example .env
    # .env에 OPENAI_API_KEY 입력
    python pipeline.py --top 10
"""
from __future__ import annotations

import argparse
import csv
import datetime
import os
import sys

# .env 수동 로드 (python-dotenv 없이)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

from fetch_top300 import fetch_top_altcoins
from agents import (
    FundamentalsAgent, SentimentAgent, NewsAgent, TechnicalAgent,
    BullDebater, BearDebater, RiskManager,
)


def analyze_coin(coin: dict) -> dict:
    """한 코인에 대해 전체 파이프라인 실행."""
    print(f"  분석 중: {coin['symbol']} ({coin['name']})")

    # 4개 분석가 병렬 실행 (순차적으로 — 필요 시 concurrent.futures로 전환)
    fundamentals = FundamentalsAgent().analyze(coin)
    sentiment = SentimentAgent().analyze(coin)
    news = NewsAgent().analyze(coin)
    technical = TechnicalAgent().analyze(coin)

    analysts = [fundamentals, sentiment, news, technical]

    # 불/베어 토론
    bull = BullDebater().analyze_with_context(coin, analysts)
    bear = BearDebater().analyze_with_context(coin, analysts)

    # 최종 결정
    decision = RiskManager().decide(coin, analysts, bull, bear)

    return {
        "id": coin["id"],
        "symbol": coin["symbol"],
        "name": coin["name"],
        "signal": decision.signal,
        "position_pct": decision.raw_data.get("position_pct", 0.0),
        "confidence": decision.confidence,
        "reasoning": decision.reasoning,
        "fundamentals": fundamentals.signal,
        "sentiment": sentiment.signal,
        "news": news.signal,
        "technical": technical.signal,
        "bull_confidence": bull.confidence,
        "bear_confidence": bear.confidence,
    }


def run(top_n: int = 10, output_csv: str | None = None) -> list[dict]:
    print(f"상위 {top_n}개 알트코인 로드 중...")
    coins = fetch_top_altcoins(top_n)
    print(f"{len(coins)}개 코인 분석 시작\n")

    results = []
    for i, coin in enumerate(coins, 1):
        print(f"[{i}/{len(coins)}]", end=" ")
        try:
            result = analyze_coin(coin)
            results.append(result)
        except Exception as e:
            print(f"    오류: {e}")
            continue

    # 강한 매수 신호 상위 출력
    buy_signals = [r for r in results if r["signal"] in ("strong_buy", "buy")]
    buy_signals.sort(key=lambda x: x["confidence"], reverse=True)

    print(f"\n=== 매수 신호 {len(buy_signals)}개 ===")
    for r in buy_signals[:10]:
        print(f"  {r['symbol']:10s} {r['signal']:12s} 신뢰도={r['confidence']:.0%} 포지션={r['position_pct']:.0%}")

    if output_csv:
        with open(output_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys() if results else [])
            writer.writeheader()
            writer.writerows(results)
        print(f"\n결과 저장: {output_csv}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=10, help="분석할 상위 코인 수 (기본: 10)")
    parser.add_argument(
        "--output",
        default=f"results_{datetime.date.today()}.csv",
        help="결과 CSV 파일명",
    )
    args = parser.parse_args()
    run(top_n=args.top, output_csv=args.output)
