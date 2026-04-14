Parameter Lab page for the AutoTrader Dashboard — a research workspace where a quant trader browses parameter search results, compares candidates, and launches new searches. This is where the autoresearch loop's output becomes interactive and explorable.

Use the existing "Obsidian Quant" design system (dark navy, teal primary, tonal surfaces, Space Grotesk + Inter + JetBrains Mono).

**PAGE STRUCTURE:**

1. **Sidebar nav (left):**
   AutoTrader logo. Dashboard | Strategies | Live Monitor | Parameter Lab (active, teal). Bottom: Docs, Settings

2. **Top bar:**
   - Breadcrumb: "Parameter Lab / Upbit MTF Search"
   - Strategy selector pill: "Upbit MTF Strategy" dropdown
   - Search run selector: "mtf-autoresearch-2026-04-12.jsonl (1,248 candidates)" dropdown
   - Right side: "새 탐색 시작" button primary teal gradient + "재시작" outline button

3. **Search Status Hero Card (full width):**
   Title: "탐색 진행 상황"
   Grid with:
   - Left: Large number "1,248 / 2,500" with progress bar teal 50% filled, subtitle "평가 완료"
   - Middle: "objective 최고값: +54,860.56" teal big monospace, delta badge "+4,470 vs 이전" teal
   - Right: Running time "2h 34m" + ETA "2h 26m 남음" small
   - Bottom row: current param set being evaluated — compact pill chips in mono "MAX_MACRO_DRAWDOWN=0.065 | STATE_CONFIRM=4 | FULL_LONG=0.92"

4. **Main content: Two columns (60/40 split):**

   **Left 60% — Top Candidates Table:**
   Title: "상위 후보 (balanced_score 기준)"
   Data table with columns:
   | 순위 | objective | 전체수익 | 테스트수익 | 최대DD | 거래수 | FULL_LONG | MAX_DD | CONFIRM |
   |------|-----------|---------|-----------|-------|------|-----------|--------|---------|
   | 1 ★  | 54,860.56 | +54,858% | +75.74% | 14.52% | 1,216 | 0.92 | 0.065 | 4 |
   | 2    | 52,341.22 | +52,339% | +72.18% | 14.88% | 1,284 | 0.92 | 0.068 | 4 |
   | 3    | 51,987.45 | +51,985% | +70.32% | 14.91% | 1,312 | 0.94 | 0.065 | 3 |
   | 4    | 50,390.18 | +50,388% | +68.45% | 14.99% | 1,458 | 0.92 | 0.070 | 3 |
   | 5    | 48,421.04 | +48,419% | +65.20% | 14.42% | 1,172 | 0.90 | 0.065 | 4 |
   Star icon on rank 1 (current default). Positive numbers teal monospace, DD in amber. Each row clickable with "적용" button on hover. Bottom: "전체 1,248건 보기" link.

   **Right 40% — Parameter Distribution Heatmap:**
   Title: "파라미터 분포 (상위 10%)"
   Heatmap grid showing MAX_MACRO_DRAWDOWN (x-axis: 0.05-0.10) vs STATE_CONFIRM_BARS (y-axis: 1-6)
   Each cell is colored by objective score (darker teal = better), with value in center
   Legend: gradient bar from dark gray (low) → teal (high)
   Below: "FULL_LONG_PCT 분포" small histogram showing peak at 0.92

5. **Compare Panel (full width, below):**
   Title: "후보 비교"
   Comparison table with 3 selected candidates side by side (current default + 2 alternatives):
   
   | 파라미터 | 현재 기본값 (1위) | 후보 A (3위) | 후보 B (8위) |
   |---------|------------------|-------------|-------------|
   | objective | 54,860.56 | 51,987.45 | 45,201.88 |
   | 전체수익 | +54,858% teal | +51,985% teal | +45,200% teal |
   | 최대DD | 14.52% amber | 14.91% amber | 12.80% teal |
   | FULL_LONG_PCT | 0.92 | 0.94 | 0.90 |
   | MAX_MACRO_DRAWDOWN | 0.065 | 0.065 | 0.058 |
   | STATE_CONFIRM_BARS | 4 | 3 | 5 |
   | MIN_REBALANCE_FRACTION | 0.12 | 0.10 | 0.15 |
   Highlight differences with subtle amber background. Bottom buttons: "후보 A 적용" outline, "후보 B 적용" outline, "기본값 유지" ghost

6. **Walk-Forward Comparison Mini-chart (bottom, full width):**
   Title: "Walk-Forward 검증 비교 (180d 창)"
   Grouped bar chart with 13 windows × 3 candidates
   - Current teal, Candidate A blue, Candidate B purple
   - Y-axis: excess return %
   - Legend right side with positive ratio numbers: "기본 69.23%" | "A 61.54%" | "B 76.92%"
