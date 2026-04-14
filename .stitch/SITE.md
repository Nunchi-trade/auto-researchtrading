# AutoTrader Dashboard — Site Vision

## 1. Overview
알고리즘 트레이딩 리서치 및 실시간 모니터링 웹 대시보드.  
Upbit MTF 전략, Upbit Spot 전략, Hyperliquid 전략을 통합 관리.

## 2. Stitch Project ID
`11874546353160517734`

## 3. Target Users
- 퀀트 트레이더 (전략 성과 분석, 파라미터 탐색)
- 운영자 (실시간 포지션/수익 모니터링)

## 4. Sitemap

| Page | File | Status |
|------|------|--------|
| Main Dashboard | index.html | [ ] |
| Strategy Detail | strategy.html | [ ] |
| Live Monitor | live.html | [ ] |
| Parameter Lab | params.html | [ ] |

## 5. Roadmap

1. [ ] Main Dashboard — 전략 현황 + 포트폴리오 요약 + 시그널 타임라인
2. [ ] Strategy Detail — 개별 전략 백테스트 결과, equity curve, 매수/매도 신호
3. [ ] Live Monitor — 실시간 Upbit 포지션, 수익, 거래 이력
4. [ ] Parameter Lab — 파라미터 서치 결과 탐색, walk-forward 차트

## 6. Tech Stack
- Frontend: Static HTML/CSS/JS (Stitch 생성 기반)
- Backend: FastAPI (Python)
- Charts: Chart.js or lightweight-charts
- Real-time: WebSocket (Upbit API 연동)
