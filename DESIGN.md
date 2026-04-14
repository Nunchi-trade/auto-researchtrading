# Design System Document: The Quantitative Terminal

## 1. Overview & Creative North Star
**Creative North Star: "The Kinetic Monolith"**
This design system moves away from the "web app" aesthetic and toward a high-performance, immersive trading environment. It treats the UI as a precision instrument rather than a collection of widgets. We break the standard grid by using **intentional asymmetry**—offsetting data streams and using varied column widths to mirror the organic flow of market liquidity. The interface should feel heavy, stable, and authoritative, using overlapping layers and tonal depth to organize high-density information without visual clutter.

## 2. Colors & Surface Architecture
The palette is rooted in deep obsidian tones, designed to reduce eye strain during 12-hour sessions while making critical data points "pop" with neon-like precision.

### Surface Hierarchy & Nesting
Instead of using lines to separate modules, we use **Tonal Layering**. 
- **Base Layer:** `surface_container_lowest` (#0B0E13) - The absolute background.
- **Section Layer:** `surface_container_low` (#191C21) - Use this for sidebar backing or large logical groupings.
- **Card/Module Layer:** `surface_container` (#1D2025) - The primary workspace for charts and tables.
- **Active/Hover Layer:** `surface_container_high` (#272A30) - For focused elements or interactive states.

### The "No-Line" Rule
**Standard 1px borders are strictly prohibited for layout sectioning.** 
To define boundaries, use background color shifts. A `surface_container` card sitting on a `surface_container_low` background creates a natural, sophisticated edge. If a separator is required for data density (e.g., table rows), use a 1px gap to reveal the background color behind, rather than drawing a line.

### The "Glass & Gradient" Rule
To inject "soul" into the terminal, main action buttons and active status indicators should use a subtle linear gradient: `primary` (#46F1C5) to `primary_container` (#00D4AA) at a 135-degree angle. Floating command palettes or tooltips must utilize **Glassmorphism**: `surface_container_highest` with 60% opacity and a 20px backdrop blur.

## 3. Typography
The typographic system creates a dual-speed reading experience: high-speed scanning for numbers and editorial clarity for research.

- **The Monospace Spine:** All numeric data, timestamps, and ticker symbols **must** use **JetBrains Mono**. This ensures vertical alignment of decimals in data tables, crucial for rapid quantitative comparison.
- **The Editorial Sans:** All labels, descriptions, and headers use **Inter**. 
- **Display & Headlines:** Use `display-sm` or `headline-lg` for portfolio totals and high-level metrics. Use `letterSpacing: "-0.02em"` on headlines to create a tighter, premium "Swiss" look.
- **Labeling:** Use `label-sm` in `on_surface_variant` (#BACAC2) for all axis labels and metadata.

## 4. Elevation & Depth
In a high-density environment, traditional drop shadows create "mud." We achieve depth through **Ambient Light**.

- **The Layering Principle:** Depth is cumulative. An "Inner Card" should always be one tier higher in the `surface_container` scale than its parent.
- **Ambient Shadows:** For floating modals, use a custom shadow: `0px 24px 48px rgba(0, 0, 0, 0.4)`. The shadow color is not black, but a darkened `surface_container_lowest` to blend into the navy-black background.
- **The "Ghost Border" Fallback:** If high-contrast environments require a border for accessibility, use the `outline_variant` at **15% opacity**. It should be felt, not seen.
- **Interaction Depth:** When a user hovers over a trade module, do not just change the color—"lift" the element by shifting the background from `surface_container` to `surface_container_high`.

## 5. Components

### Trading-Specific Primitives
- **Data Tables:** Forbid horizontal dividers. Use `surface_container_low` for the header row and a subtle `surface_container_highest` background on hover. Use JetBrains Mono for all cell values.
- **Price Action Chips:** Use `primary` (#46F1C5) for gains and `tertiary_container` (#FFA3A3) for losses. The chip background should be 10% opacity of the text color to maintain legibility.
- **Action Buttons:** 
    - **Primary:** Gradient fill (Primary to Primary Container).
    - **Ghost (Secondary):** No background, `outline` color text, transforms to 10% opacity white on hover.
- **Input Fields:** Use `surface_container_lowest` for the field fill to create an "inset" look against the `surface_container` card. Use a `primary` 2px bottom-bar for the focus state.
- **Candlestick Charts:** Use `primary_container` for bullish candles and `error` (#FFB4AB) for bearish. Avoid pure red/green; use the refined teal/coral palette provided.

### Specialized Components
- **The "Live Pulse" Indicator:** A 4px glowing dot using the `primary` color with a `box-shadow: 0 0 10px #00D4AA`.
- **The Research Terminal Sidebar:** A "nested" vertical strip using `surface_container_low` that houses research notes in `body-sm` Inter typography.

## 6. Do's and Don'ts

### Do
- **DO** use vertical whitespace (16px, 24px, 32px) to group content instead of lines.
- **DO** align all decimal points in tables using the tabular figures feature of JetBrains Mono.
- **DO** use `muted` (#4A5568) text for non-essential information like "Updated 2m ago."
- **DO** overlap elements (e.g., a chart legend slightly overlapping the chart area) to create a custom, high-end feel.

### Don'ts
- **DON'T** use 100% white (#FFFFFF). It causes "haloing" in dark mode. Use `on_surface` (#E1E2EA).
- **DON'T** use standard 400ms easing. Use `cubic-bezier(0.2, 0, 0, 1)` (Stiff/Professional) for all transitions to make the terminal feel responsive.
- **DON'T** use rounded corners larger than 8px. This is a professional tool; excessively round "bubbly" corners diminish the sense of precision.
- **DON'T** use shadows on flat cards. Shadows are reserved strictly for floating overlays (modals/tooltips).