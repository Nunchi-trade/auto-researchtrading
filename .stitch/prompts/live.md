Live Monitor page for the AutoTrader Dashboard — real-time Upbit trading operations view. This is where a trader watches live positions, monitors strategy state, and verifies that orders are executing correctly. This page assumes the Upbit API is connected and streaming data via WebSocket.

Use the existing "Obsidian Quant" design system (dark navy background, teal primary, Space Grotesk + Inter + JetBrains Mono, tonal surfaces, no 1px borders).

**PAGE STRUCTURE:**

1. **Sidebar nav (left, same layout):**
   AutoTrader logo. Tabs: Dashboard | Strategies | Live Monitor (active, teal highlight) | Parameter Lab. Bottom Docs, Settings

2. **Top bar:**
   - Breadcrumb: "Live Monitor / Upbit KRW-BTC"
   - Exchange connection status cluster: green pulsing dot + "Upbit WebSocket 연결됨" text + "latency 42ms" small gray
   - Right: Strategy kill switch — red outline button "긴급 정지" with shield icon
   - "마지막 업데이트: 방금" auto-refresh indicator

3. **Live Price Ticker (hero, full width):**
   Large centered monospace: "₩142,350,000" with "+2.34%" teal badge
   Sub-row: 시가 ₩139,120,000 | 고가 ₩143,800,000 | 저가 ₩138,900,000 | 거래대금 ₩2,845억
   Pulsing green dot indicating live updates

4. **Current Position Panel (full width, prominent):**
   Title: "현재 포지션"
   Large grid with:
   - Left card (30%): Strategy state "FULL_LONG" huge teal badge + "Upbit MTF" label
   - Middle card (40%): 
     - Position value "₩48,619,424" large monospace
     - Below: "92% of equity" small gray + horizontal progress bar 92% teal
     - Coins held: "0.3421 BTC"
     - Avg entry: "₩141,200,000"
   - Right card (30%):
     - Unrealized P&L: "+₩395,240" teal large
     - "+0.81%" teal badge
     - Current price vs entry: "+0.81% above entry"
     - Time in position: "4h 32m"

5. **Two-column layout:**

   **Left 60% — Real-time Price Chart:**
   Title: "KRW-BTC 실시간 가격 차트 (5분봉)"
   Large candlestick chart placeholder with dark background:
   - Green and red candles (teal for bull, red for bear)
   - EMA lines: EMA 8 (teal), EMA 21 (light gray)
   - Volume bars at bottom
   - Strategy signal markers: teal arrow up at BUY, red arrow down at SELL, amber circle at REDUCE
   - Timeframe selector: "1m | 5m | 15m | 1h | 4h" (5m active)
   - Right-side: current macro/micro strength vertical gauge bars teal

   **Right 40% — Order Execution Log:**
   Title: "주문 실행 로그"
   Scrollable terminal-style list (JetBrains Mono):
   Each row: [timestamp] [status dot] [action] [size] [price] [fee]
   Example entries (teal dot = filled, amber = partial, red = rejected):
   - 09:15:23  ●  BUY 0.0834 BTC @ ₩141,200,000  fee ₩42,840  FILLED
   - 08:45:12  ●  BUY 0.0412 BTC @ ₩141,050,000  fee ₩21,120  FILLED
   - 08:45:11  ◐  PARTIAL 0.0088/0.05 @ ₩141,080,000  fee ₩4,521  PARTIAL
   - 08:15:00  ●  SELL 0.0521 BTC @ ₩138,500,000  fee ₩26,720  FILLED
   Bottom: "Upbit 주문창 열기" outline button

6. **Bottom — Risk & System Metrics Row (3 cards):**
   
   **Card A — 리스크 게이지:**
   - 현재 낙폭 "-1.2%" small teal (within tolerance)
   - Max DD 한도 "-6.5%" (MAX_MACRO_DRAWDOWN)
   - Horizontal bar: current/limit with filled portion teal then transitioning amber toward threshold
   - Label: "정상 범위" teal

   **Card B — 오늘 거래 요약:**
   - 총 주문 수: "4"
   - 체결: "3" / 대기: "1" / 거부: "0"
   - 오늘 수수료: "₩94,680"
   - 오늘 실현 손익: "+₩247,800" teal

   **Card C — 시스템 상태:**
   - API connection: 🟢 정상
   - WebSocket: 🟢 정상 (42ms)
   - Strategy engine: 🟢 실행 중
   - Data pipeline: 🟢 정상
   - Last error: "없음" gray
