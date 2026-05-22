"""
Predefined market scenario seeds for MiroFish world model simulation.

Each scenario defines seed documents that describe a market event or regime.
MiroFish agents react to these seeds, producing sentiment trajectories that
get translated into synthetic price data via the bridge.
"""

import os
import json
from dataclasses import dataclass, field
from pathlib import Path

SCENARIO_CACHE = Path(os.path.expanduser("~")) / ".cache" / "equities-autotrader" / "scenarios"


@dataclass
class ScenarioSeed:
    name: str
    description: str
    seed_docs: list
    agent_count: int = 50
    rounds: int = 10
    expected_impact: dict = field(default_factory=dict)
    # expected_impact maps symbol -> float multiplier
    # positive = bullish pressure, negative = bearish, magnitude = intensity


# ---------------------------------------------------------------------------
# Predefined scenarios
# ---------------------------------------------------------------------------

SCENARIOS = {
    "fed_emergency_hike": ScenarioSeed(
        name="fed_emergency_hike",
        description="Fed raises rates to 7% in emergency session. Bank stress intensifies, tech sells off hard.",
        seed_docs=[
            """BREAKING: Federal Reserve Emergency Rate Decision — March 2025

The Federal Reserve announced an emergency 200 basis point rate increase, bringing the federal funds rate to 7.25%. Chair Powell cited "persistent and accelerating inflation that threatens economic stability." This is the largest single rate hike since the Volcker era.

Treasury yields surged immediately. The 10-year yield hit 6.8%, the highest since 2000. The 2-year yield inverted further against the 10-year, deepening recession signals.

Major banks reported unrealized losses on bond portfolios exceeding $400 billion collectively. Regional bank stocks fell 15-20% in after-hours trading. Credit default swap spreads on major financial institutions widened significantly.

Technology companies with high debt loads and negative free cash flow face severe refinancing risks. Venture capital funding has effectively frozen. Multiple unicorns announced emergency laydowns.""",

            """Market Analysis: Sector Impact of Emergency Rate Hike

MOST VULNERABLE:
- Technology (QQQ, AAPL, NVDA): Growth stocks with high P/E ratios face severe multiple compression. Discount rates surge, making future earnings worth far less today. Cloud computing companies with debt-funded growth are particularly exposed.
- Real Estate: Mortgage rates above 9% effectively freeze housing market. REITs face refinancing crisis.
- Small Caps (IWM): Higher rates disproportionately hurt smaller companies with floating-rate debt.

RELATIVELY RESILIENT:
- Energy (XLE): Oil demand remains steady, and energy companies have low debt and high free cash flow.
- Financials (XLF, JPM): Net interest margins expand with higher rates, but credit losses from potential recession offset this. Mixed outlook.
- Treasuries (TLT): Paradoxically, long-duration bonds fall sharply on rate hike but then rally as recession fears dominate. Flight to safety.
- Healthcare (UNH): Defensive sector with inelastic demand. Less rate-sensitive.

MARKET STRUCTURE:
Expect 5-10% drawdown in broad indices (SPY) within days. Volatility (VIX) likely to spike above 40. Liquidity deterioration in credit markets. Potential for margin calls triggering forced selling cascade.""",
        ],
        expected_impact={
            "SPY": -1.5, "QQQ": -2.5, "IWM": -2.0,
            "XLE": 0.3, "XLF": -0.5, "TLT": -1.0,
            "AAPL": -2.0, "NVDA": -3.0, "JPM": -0.8, "UNH": -0.3,
        },
    ),

    "tech_bubble_burst": ScenarioSeed(
        name="tech_bubble_burst",
        description="AI hype cycle peaks and collapses. NVDA guidance miss triggers broad tech selloff.",
        seed_docs=[
            """NVIDIA Q4 Earnings Shock: Revenue Guidance Cut 40%

NVIDIA reported Q4 earnings that missed estimates by 15%, but the real shock was forward guidance. The company cut Q1 revenue guidance by 40%, citing "significant inventory correction across data center customers" and "slower-than-expected enterprise AI adoption."

CEO Jensen Huang admitted that hyperscaler customers had over-ordered GPUs in 2024, creating an inventory glut. Microsoft, Google, and Amazon all signaled they would reduce AI capex by 30-50% in the coming quarters.

NVDA stock fell 35% in extended trading, wiping out $800 billion in market cap. The ripple effects were immediate: AMD fell 20%, SMCI fell 45%, and the broader semiconductor index dropped 25%.

Analysts who had been bullish reversed course. Multiple firms downgraded the entire AI supply chain. The narrative shifted from "AI is transforming everything" to "AI spending was a bubble."

This triggered a broader re-evaluation of technology valuations. Mega-cap tech stocks that had carried the market in 2024 faced selling pressure as investors rotated into defensive sectors.""",
        ],
        expected_impact={
            "SPY": -1.0, "QQQ": -3.0, "IWM": -0.5,
            "XLE": 0.5, "XLF": 0.3, "TLT": 1.5,
            "AAPL": -1.5, "NVDA": -4.0, "JPM": 0.3, "UNH": 0.8,
        },
    ),

    "energy_crisis": ScenarioSeed(
        name="energy_crisis",
        description="Middle East conflict escalation, Strait of Hormuz blockade, oil to $150.",
        seed_docs=[
            """BREAKING: Strait of Hormuz Blockade — Oil Surges Past $150

A major military escalation in the Middle East has effectively blocked the Strait of Hormuz, through which 20% of the world's oil supply passes. Multiple tankers have been attacked, and maritime insurance rates have soared 500%.

Oil prices surged to $153 per barrel, the highest in history. Natural gas prices doubled. Gasoline at the pump hit $7 per gallon in the US.

The energy sector is the clear beneficiary. Major oil companies (ExxonMobil, Chevron, ConocoPhillips) saw stocks surge 20-30% as their existing production became enormously profitable.

However, the broader economy faces severe headwinds. Transportation costs are spiking, consumer spending is being squeezed, and inflation expectations are surging. The Fed is trapped between fighting inflation and supporting a weakening economy.

Airlines, logistics companies, and energy-intensive manufacturers are particularly vulnerable. Consumer discretionary spending is expected to decline sharply as gasoline costs absorb household budgets.""",
        ],
        expected_impact={
            "SPY": -1.0, "QQQ": -1.5, "IWM": -1.5,
            "XLE": 3.0, "XLF": -0.5, "TLT": 0.5,
            "AAPL": -1.0, "NVDA": -1.0, "JPM": -0.5, "UNH": -0.3,
        },
    ),

    "recession_signal": ScenarioSeed(
        name="recession_signal",
        description="Yield curve deeply inverts, unemployment rises to 6%, defensive rotation.",
        seed_docs=[
            """Economic Data Confirms Recession: Unemployment Surges to 6%

The Bureau of Labor Statistics reported a shocking jump in unemployment from 4.2% to 6.0%, the largest single-month increase since the 2008 financial crisis. Non-farm payrolls declined by 350,000, far worse than the consensus estimate of +50,000.

The yield curve, already inverted, deepened further. The 2y-10y spread reached -120 basis points, the most inverted since 1980. Credit spreads widened across investment grade and high yield bonds.

Consumer confidence collapsed to 2008 levels. Retail sales declined 3% month-over-month. Housing starts fell to their lowest since 2011.

Investors are rotating aggressively into defensive sectors: utilities, healthcare, and consumer staples. Gold hit new all-time highs. Treasury bonds rallied sharply as investors priced in aggressive Fed rate cuts.

Cyclical sectors — technology, industrials, financials, and consumer discretionary — face significant downside as earnings estimates are slashed. Small caps are particularly vulnerable given their domestic exposure and higher debt loads.""",
        ],
        expected_impact={
            "SPY": -1.5, "QQQ": -1.5, "IWM": -2.5,
            "XLE": -1.0, "XLF": -2.0, "TLT": 2.0,
            "AAPL": -1.0, "NVDA": -1.5, "JPM": -2.0, "UNH": 0.5,
        },
    ),

    "bull_euphoria": ScenarioSeed(
        name="bull_euphoria",
        description="Soft landing confirmed, rate cuts begin, risk-on rally across all sectors.",
        seed_docs=[
            """Fed Confirms Soft Landing: Rate Cuts Begin, Markets Surge

The Federal Reserve announced a 50 basis point rate cut, signaling the start of an easing cycle. Chair Powell declared "inflation has been durably brought to target while the labor market remains healthy — the soft landing is achieved."

Markets reacted with euphoria. The S&P 500 surged 5% in two days, reaching new all-time highs. The Nasdaq rallied 7%. Small caps (Russell 2000) outperformed with an 8% gain as lower rates disproportionately benefit smaller companies.

Every sector participated. Technology led on growth expectations, financials rallied on loan growth prospects, and even traditionally defensive sectors gained as the overall pie grew.

Corporate earnings revisions turned sharply positive. CEO confidence surveys hit multi-year highs. Merger and acquisition activity surged as cheap financing returned. IPO markets reopened with multiple successful listings.

International investors poured capital into US markets, strengthening the dollar. Risk premiums compressed across all asset classes. The VIX fell to 11, the lowest since pre-pandemic.""",
        ],
        expected_impact={
            "SPY": 2.0, "QQQ": 2.5, "IWM": 3.0,
            "XLE": 1.0, "XLF": 2.0, "TLT": 0.5,
            "AAPL": 2.0, "NVDA": 3.0, "JPM": 2.5, "UNH": 1.0,
        },
    ),

    "flash_crash": ScenarioSeed(
        name="flash_crash",
        description="Algorithmic cascade triggers 10% intraday drop, followed by rapid V-recovery.",
        seed_docs=[
            """Flash Crash: S&P 500 Drops 10% in 45 Minutes, Then Recovers

At 2:15 PM ET, a cascading series of algorithmic selling orders triggered the most violent intraday crash since 2010. The S&P 500 fell 10.3% in just 45 minutes before circuit breakers halted trading.

The trigger appears to have been a large institutional order that overwhelmed market-maker liquidity. As prices fell, systematic trend-following strategies added selling pressure. Risk parity funds automatically deleveraged, and margin calls forced liquidation of leveraged positions.

After the 15-minute trading halt, markets reopened and staged a dramatic V-shaped recovery. By market close, the S&P 500 had recovered to just -2.1% from the open. Many stocks that fell 20-30% during the crash ended the day near flat.

However, the damage was done for many leveraged traders and systematic strategies. Estimated losses from stop-loss triggers exceeded $200 billion. Multiple hedge funds reported significant drawdowns from positions that were stopped out at the bottom.

The crash-and-recovery pattern creates unique challenges for trading strategies: tight stops get whipsawed, while strategies without stops face terrifying drawdowns. Only strategies with wide stops or no stops survived without damage.""",
        ],
        expected_impact={
            "SPY": -0.5, "QQQ": -0.8, "IWM": -1.0,
            "XLE": -0.3, "XLF": -0.5, "TLT": 0.5,
            "AAPL": -0.5, "NVDA": -1.0, "JPM": -0.5, "UNH": -0.3,
        },
    ),

    "inflation_return": ScenarioSeed(
        name="inflation_return",
        description="CPI surprises at 8%+, bonds crash, commodities and real assets surge.",
        seed_docs=[
            """CPI Shock: Inflation Surges Back to 8.3%

The Bureau of Labor Statistics reported CPI at 8.3% year-over-year, the highest since the 2022 peak. Core CPI hit 6.1%. The report shattered the disinflation narrative that had supported markets for months.

The causes were multiple: a resurgence in energy prices, persistent shelter inflation, and a new wave of supply chain disruptions from geopolitical tensions. Wages were rising faster than expected, creating a potential wage-price spiral.

Bond markets sold off violently. The 10-year Treasury yield surged 80 basis points in a week to 5.8%. The long-end (TLT) fell 15%. Rate-cut expectations were completely repriced — markets now expect hikes instead of cuts.

Commodities rallied broadly. Gold hit $2,800. Oil surged to $110. Agricultural commodities rose 20%. TIPS breakevens widened dramatically.

Equity markets faced severe pressure. Growth stocks with high duration were hit hardest. Value stocks and commodity producers outperformed on a relative basis. Energy was the only sector in positive territory.""",
        ],
        expected_impact={
            "SPY": -1.5, "QQQ": -2.5, "IWM": -1.5,
            "XLE": 2.5, "XLF": -0.5, "TLT": -3.0,
            "AAPL": -2.0, "NVDA": -2.5, "JPM": -0.3, "UNH": -0.5,
        },
    ),

    "sector_rotation": ScenarioSeed(
        name="sector_rotation",
        description="Massive growth-to-value rotation. Financials and energy lead, tech lags.",
        seed_docs=[
            """The Great Rotation: Value Crushes Growth by 20% in One Quarter

A historic sector rotation is underway. After years of growth stock dominance, investors are aggressively shifting capital from technology and growth names into financials, energy, industrials, and healthcare.

The catalyst: rising rates favor value sectors with near-term earnings over growth sectors dependent on distant future cash flows. Banks benefit from wider net interest margins. Energy companies generate enormous free cash flow at current commodity prices. Healthcare trades at reasonable multiples with stable demand.

Meanwhile, technology faces multiple headwinds: regulatory scrutiny, slowing revenue growth, and compressed multiples as discount rates rise. The Nasdaq has underperformed the Dow by 15% this quarter.

Small caps (IWM) are outperforming large caps as the rotation favors domestically-oriented value companies over mega-cap tech. The equal-weight S&P 500 is crushing the cap-weighted version.

JPMorgan, ExxonMobil, and UnitedHealth are among the biggest beneficiaries. Apple and NVIDIA are among the biggest laggards. TLT is roughly flat as rate expectations stabilize.""",
        ],
        expected_impact={
            "SPY": 0.3, "QQQ": -2.0, "IWM": 1.5,
            "XLE": 2.0, "XLF": 2.0, "TLT": 0.0,
            "AAPL": -1.5, "NVDA": -2.0, "JPM": 2.5, "UNH": 1.5,
        },
    ),
}


class ScenarioManager:
    """Manage scenario generation, caching, and retrieval."""

    def __init__(self, cache_dir=None):
        self.cache_dir = Path(cache_dir) if cache_dir else SCENARIO_CACHE
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def list_scenarios(self):
        """List all available scenario names."""
        return list(SCENARIOS.keys())

    def get_scenario(self, name):
        """Get a scenario seed by name."""
        if name not in SCENARIOS:
            raise KeyError(f"Unknown scenario: {name}. Available: {self.list_scenarios()}")
        return SCENARIOS[name]

    def get_cache_path(self, name):
        """Get cache directory for a scenario."""
        return self.cache_dir / name

    def is_cached(self, name):
        """Check if scenario data is already cached."""
        cache_path = self.get_cache_path(name)
        if not cache_path.exists():
            return False
        # Check at least one parquet exists
        return any(cache_path.glob("*_1d.parquet"))

    def list_cached(self):
        """List scenarios that have cached data."""
        return [name for name in SCENARIOS if self.is_cached(name)]

    def save_metadata(self, name, metadata):
        """Save scenario metadata alongside cached data."""
        cache_path = self.get_cache_path(name)
        cache_path.mkdir(parents=True, exist_ok=True)
        (cache_path / "metadata.json").write_text(json.dumps(metadata, indent=2))

    def load_metadata(self, name):
        """Load scenario metadata."""
        meta_path = self.get_cache_path(name) / "metadata.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text())
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage MiroFish scenarios")
    parser.add_argument("--list", action="store_true", help="List all scenarios")
    parser.add_argument("--describe", type=str, help="Describe a scenario")
    parser.add_argument("--cached", action="store_true", help="List cached scenarios")
    args = parser.parse_args()

    mgr = ScenarioManager()

    if args.list:
        print("Available scenarios:")
        for name in mgr.list_scenarios():
            s = SCENARIOS[name]
            cached = " [CACHED]" if mgr.is_cached(name) else ""
            print(f"  {name:25s} {s.description}{cached}")

    elif args.describe:
        s = mgr.get_scenario(args.describe)
        print(f"Scenario: {s.name}")
        print(f"Description: {s.description}")
        print(f"Agents: {s.agent_count}, Rounds: {s.rounds}")
        print(f"Expected impact:")
        for sym, impact in s.expected_impact.items():
            direction = "bullish" if impact > 0 else "bearish" if impact < 0 else "neutral"
            print(f"  {sym:6s} {impact:+.1f} ({direction})")

    elif args.cached:
        cached = mgr.list_cached()
        if cached:
            print(f"Cached scenarios: {', '.join(cached)}")
        else:
            print("No cached scenarios. Run scenarios first.")

    else:
        parser.print_help()
