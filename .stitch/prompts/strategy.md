Strategy Detail page for the AutoTrader Dashboard — deep dive into a single algorithmic trading strategy (MTF, Spot, or Hyperliquid). This page is where a quant trader analyzes backtest results, inspects buy/sell signals, and manages strategy parameters.

Use the existing "Obsidian Quant" design system from this project (dark navy background, teal primary #00D4AA, Space Grotesk + Inter + JetBrains Mono fonts, no 1px borders, tonal surface hierarchy).

**PAGE STRUCTURE:**

1. **Sidebar navigation (left, same as Dashboard):**
   AutoTrader logo. Tabs: Dashboard | Strategies (active, teal highlight) | Live Monitor | Parameter Lab. Bottom: Docs, Settings

2. **Breadcrumb + Strategy Selector header:**
   - Path: "Strategies / Upbit MTF" 
   - Strategy picker dropdown: "Upbit MTF Strategy" with chevron
   - Tab switcher: "Overview | Signals | Backtest | Parameters"
   - Right side: Date range picker "2018-01 ~ 2025-10" and "백테스트 재실행" button (primary teal gradient)

3. **Strategy Overview Card (full width):**
   - Strategy name large: "Upbit MTF Strategy"
   - Subtitle: "Multi-Timeframe State Machine — flat → reduced_high → full_long"
   - Current state badge: "FULL_LONG" teal pill
   - Three columns of metrics in monospace:
     - Left: 전체초과수익 "+54,858.37%" teal, 테스트수익 "+75.74%" teal, 거래수 "1,216"
     - Middle: 최대낙폭 "14.52%" amber, 테스트DD "7.09%" amber, Sharpe "4.13"
     - Right: 승률 "62%", Profit Factor "2.48", 평균 보유 "18h"

4. **Two-column layout (split 50/50):**

   **Left — Equity Curve Chart:**
   Title: "누적 수익 곡선 (Strategy vs Buy & Hold)"
   Large dark chart area. 
   - Teal solid line dramatically rising (MTF strategy)
   - Gray dashed line (Buy & Hold benchmark)
   - X-axis: year labels 2018-2025
   - Y-axis: logarithmic % scale
   - Annotations at key peaks and drawdown troughs
   - Legend top-right: Strategy (teal), Buy & Hold (gray dashed), Drawdown (amber fill)
   - Period selector chips below: "1W | 1M | 3M | 6M | 1Y | ALL" (ALL active)

   **Right — Signals Table:**
   Title: "매매 신호 이력 (최근 20건)"
   Scrollable data table with columns:
   | # | 시점 | 액션 | 가격 | 사이즈 | 상태 전환 | 결과 |
   |---|------|------|------|-------|----------|------|
   | 1 | 2026-04-14 09:15 | BUY | ₩141,200,000 | 92% | flat→full_long | +2.1% |
   | 2 | 2026-04-13 14:30 | REDUCE | ₩138,500,000 | 57.6% | full_long→reduced | — |
   | 3 | 2026-04-12 11:00 | BUY | ₩135,800,000 | 92% | reduced→full_long | +3.5% |
   | 4 | 2026-04-10 08:45 | SELL | ₩132,800,000 | 0% | full_long→flat | +1.2% |
   Each action has colored badge (BUY teal, SELL red, REDUCE amber). State transitions in small gray text. Results in teal/red.
   Bottom link: "전체 1,216건 보기"

5. **Walk-Forward Validation Panel (full width, below):**
   Title: "Walk-Forward 검증"
   Two side-by-side sub-cards:
   
   **Sub-card A — "180d 테스트 창 (2y 학습)":**
   - Big number: "69.23% 양수" teal
   - "13개 창 중 9개" small text
   - Mini bar chart: 13 vertical bars, each bar height = excess return, positive bars teal, negative bars amber
   - Stats row: 평균 초과수익 "-4.87%", 최소 "-176.22%", 최대DD "10.04%"
   
   **Sub-card B — "1y 테스트 창 (2y 학습)":**
   - Big number: "50.00% 양수" amber (borderline)
   - "6개 창 중 3개"  
   - Mini bar chart: 6 bars
   - Stats: 평균 "+8.48%" teal, 최소 "-27.33%", 최대DD "10.04%"

6. **Parameter Snapshot (compact card, bottom):**
   Title: "현재 파라미터" with "편집" button outline
   Two-column grid of param/value pairs in monospace:
   FULL_LONG_PCT: 0.92 | MAX_MACRO_DRAWDOWN: 0.065
   REDUCED_PCT: 0.576 | STATE_CONFIRM_BARS: 4
   MACRO_FULL_THRESHOLD: 0.58 | MIN_STATE_HOLD_BARS: 1
   MICRO_FULL_THRESHOLD: 0.50 | MIN_REBALANCE_FRACTION: 0.12
   MICRO_ENTER_FULL: 0.52 | MICRO_EXIT_FULL: 0.46
