---
page: index
---
Professional algorithmic trading research & live monitor dashboard for a quant trader managing multiple crypto strategies on Upbit exchange.

**DESIGN SYSTEM (REQUIRED):**
- Platform: Web, Desktop-first (1440px)
- Color Mode: DARK
- Background: Deep navy-black #0B0E13
- Card surface: #141820 with 1px solid border #2A2F3A
- Primary accent: #00D4AA (teal-green — gains, bull state, active)
- Danger: #FF4757 (red-orange — losses, drawdown, sell signals)
- Warning: #FFB800 (amber — reduced position, caution, drawdown metrics)
- Text primary: #E8EDF2, Text secondary: #8B9AB0, Text muted: #4A5568
- Numbers font: JetBrains Mono or monospace
- Body font: Inter or system sans-serif
- Card radius: 8px, Badge radius: 4px
- Elevation: box-shadow 0 2px 8px rgba(0,0,0,0.4)
- Vibe: Professional terminal, data-dense but clean, similar to trading platforms

**PAGE STRUCTURE:**

1. **Sticky Top Navigation (full width, #0D1117 bg, border-bottom #2A2F3A):**
   - Left: "AutoTrader" wordmark with small candlestick chart icon, teal accent
   - Center: Tab navigation — Dashboard (active, teal underline) | Strategies | Live Monitor | Parameter Lab
   - Right: KRW-BTC live price "₩142,350,000" in white monospace + "+2.34%" green badge + green status dot "연결됨"

2. **Portfolio KPI Row (4 cards, 25% each, padding 24px):**
   - 총 자산: "₩52,847,200" large monospace, small gray label, up-arrow sparkline
   - 오늘 수익: "+₩1,247,800" teal colored, "(+2.41%)" badge teal bg, up arrow icon
   - 현재 낙폭: "-7.09%" amber colored, progress bar showing 7.09/15 (max DD constraint), "최대 14.52%" gray label
   - 활성 전략: "2 / 3" large, "전략 운영 중" label, 2 teal dots 1 gray dot icons

3. **Strategy State Panel (title "전략 현재 상태", 3 equal cards):**

   **Card A — Upbit MTF:**
   - Title "MTF 전략" + small tag "멀티타임프레임"
   - Large state badge: "FULL_LONG" with teal background, white text
   - Horizontal position bar: 92% filled gradient teal-to-teal-dark, "포지션 92%" label
   - Two horizontal mini-bars: "매크로 강도 0.73" teal, "마이크로 강도 0.67" teal
   - Bottom: "KRW-BTC ₩48,619,424" small gray

   **Card B — Upbit Spot:**
   - Title "Spot 전략" + tag "현물"
   - State badge: "HOLDING" teal
   - Position bar: 45% filled
   - Stats row: "Sharpe 2.19" | "승률 34.8%" | "최근신호: BUY 4h ago"
   - Bottom: "KRW-BTC ₩23,781,240"

   **Card C — Hyperliquid:**
   - Title "Hyperliquid" + tag "선물"
   - State badge: "INACTIVE" gray, opacity 60%
   - Position bar: empty/gray
   - Dimmed gray content: "0% 포지션", "준비 중"
   - Button: "활성화" outline style

4. **Two-Column Content (60/40 split):**

   **Left — 최근 매매 신호 (Signal Timeline):**
   Vertical list of signal rows, each with:
   - Colored left border + dot (green=BUY, red=SELL, amber=REDUCE)
   - Row content: [Action badge] [Asset] [Price in mono] [Time] [Strategy tag] [Change arrow]
   Example rows:
   - 🟢 BUY    KRW-BTC  ₩141,200,000  2026-04-14 09:15  MTF  +0.92 포지션
   - 🔴 SELL   KRW-BTC  ₩138,500,000  2026-04-13 14:30  Spot exit 완료 +2.1%
   - 🟡 REDUCE KRW-BTC  ₩134,200,000  2026-04-11 08:45  MTF  0.92→0.576
   - 🟢 BUY    KRW-BTC  ₩132,800,000  2026-04-10 11:00  MTF  +0.92 포지션
   "전체 보기" link at bottom

   **Right — 전략 성과 요약:**
   Compact data table:
   | 전략 | 전체초과수익 | 테스트수익 | 최대DD | 거래수 |
   |------|------------|---------|------|-----|
   | MTF  | +54,858%   | +75.74% | 14.52% | 1,216 |
   | Spot | +92.8%     | +25.2%  | 8.16%  | 612   |
   Positive numbers teal, DD values amber, all monospace
   
   Below table: "Walk-Forward 검증" section
   - "180d 창: 69.23% 양수" progress badge
   - "1y 창: 50.00% 양수" progress badge

5. **Full-Width Equity Curve Section:**
   Card with title "MTF 전략 누적 수익 (전체 기간)" + "vs Buy & Hold" legend
   - Dark chart area (#0D1117 bg)
   - Teal solid line dramatically rising (strategy) 
   - Gray dashed line more modest (buy & hold)
   - X-axis: year labels 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025
   - Y-axis: % return labels
   - Subtle grid lines #1A2030
   - Two annotation labels: peak return "+54,858%" teal, and current drawdown "-7.09%" amber arrow
