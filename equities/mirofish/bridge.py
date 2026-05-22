"""
Scenario Bridge: converts MiroFish simulation output into synthetic OHLCV data
matching the format expected by prepare.load_data().

Two modes:
  1. Sentiment Modulation (default): takes real historical prices and applies
     sentiment-driven return adjustments based on MiroFish output.
  2. Fallback (no MiroFish): uses expected_impact directly from scenario seeds
     to generate synthetic data without running MiroFish.
"""

import os
import sys
import re
import numpy as np
import pandas as pd
from pathlib import Path

# Import from parent package
sys.path.insert(0, str(Path(__file__).parent.parent))
from prepare import SYMBOLS, TRAIN_START, TRAIN_END, VAL_START, VAL_END, TEST_START, TEST_END, DATA_DIR

from .scenarios import ScenarioSeed, ScenarioManager, SCENARIO_CACHE


# ---------------------------------------------------------------------------
# Sentiment extraction from MiroFish output
# ---------------------------------------------------------------------------

BULLISH_KEYWORDS = [
    "rally", "surge", "gain", "bull", "optimist", "buy", "long", "growth",
    "recover", "boom", "profit", "upside", "breakout", "strong", "positive",
    "outperform", "rise", "climb", "advance", "soar",
]

BEARISH_KEYWORDS = [
    "crash", "sell", "bear", "pessimist", "short", "decline", "loss",
    "recession", "fear", "panic", "collapse", "downturn", "risk",
    "negative", "drop", "fall", "plunge", "slump", "weak", "underperform",
]


def extract_sentiment_from_text(text):
    """
    Extract sentiment score from text using keyword matching.
    Returns float in [-1, 1].
    """
    text_lower = text.lower()
    bull_count = sum(1 for kw in BULLISH_KEYWORDS if kw in text_lower)
    bear_count = sum(1 for kw in BEARISH_KEYWORDS if kw in text_lower)
    total = bull_count + bear_count
    if total == 0:
        return 0.0
    return (bull_count - bear_count) / total


def extract_sentiment_trajectory(timeline, agent_actions=None):
    """
    Extract per-round sentiment from MiroFish timeline and actions.

    Returns DataFrame with columns: round, sentiment, dispersion.
    """
    rounds = []
    for i, entry in enumerate(timeline):
        text = ""
        if isinstance(entry, dict):
            text = entry.get("summary", entry.get("content", str(entry)))
        elif isinstance(entry, str):
            text = entry

        sentiment = extract_sentiment_from_text(text)
        rounds.append({"round": i, "sentiment": sentiment})

    if not rounds:
        rounds = [{"round": 0, "sentiment": 0.0}]

    df = pd.DataFrame(rounds)
    return df


# ---------------------------------------------------------------------------
# Sentiment from expected_impact (fallback, no MiroFish needed)
# ---------------------------------------------------------------------------

def sentiment_from_expected_impact(scenario, num_rounds=10):
    """
    Generate a synthetic sentiment trajectory from scenario expected_impact.
    Useful when MiroFish is not running — uses the scenario's predefined
    directional biases to create plausible sentiment curves.
    """
    # Average impact across symbols as base sentiment
    impacts = list(scenario.expected_impact.values())
    base_sentiment = np.mean(impacts) / max(abs(max(impacts, key=abs)), 1)

    # Create trajectory: starts neutral, builds to peak sentiment, holds
    rounds = []
    for i in range(num_rounds):
        t = i / max(num_rounds - 1, 1)
        # Sigmoid-like buildup
        intensity = 1 / (1 + np.exp(-6 * (t - 0.3)))
        sentiment = base_sentiment * intensity
        # Add slight noise
        sentiment += np.random.normal(0, 0.05)
        sentiment = max(-1.0, min(1.0, sentiment))
        rounds.append({"round": i, "sentiment": sentiment})

    return pd.DataFrame(rounds)


# ---------------------------------------------------------------------------
# Price synthesis: Sentiment Modulation
# ---------------------------------------------------------------------------

def modulate_historical_prices(base_data, sentiment_df, scenario, amplification=2.0):
    """
    Take real historical prices and modulate returns based on sentiment trajectory.

    Args:
        base_data: {symbol: DataFrame} from prepare.load_data()
        sentiment_df: DataFrame with (round, sentiment) columns
        scenario: ScenarioSeed with expected_impact per symbol
        amplification: base multiplier for sentiment effect

    Returns:
        {symbol: DataFrame} with same format, modulated prices.
    """
    result = {}
    num_rounds = len(sentiment_df)

    for symbol, df in base_data.items():
        df = df.copy()
        n_bars = len(df)
        if n_bars == 0:
            result[symbol] = df
            continue

        # Interpolate sentiment from rounds to bars
        round_indices = np.linspace(0, n_bars - 1, num_rounds)
        sentiments = sentiment_df["sentiment"].values
        bar_sentiment = np.interp(np.arange(n_bars), round_indices, sentiments)

        # Per-symbol amplification from expected_impact
        symbol_impact = scenario.expected_impact.get(symbol, 0.0)
        effective_amp = amplification * abs(symbol_impact) if symbol_impact != 0 else amplification * 0.3
        direction = np.sign(symbol_impact) if symbol_impact != 0 else 1.0

        # Compute base daily returns
        closes = df["close"].values.astype(float)
        base_returns = np.diff(closes) / closes[:-1]

        # Compute base daily vol for scaling
        base_vol = np.std(base_returns) if len(base_returns) > 1 else 0.01

        # Apply sentiment-driven return adjustments
        sentiment_returns = bar_sentiment[1:] * direction * effective_amp * base_vol
        modulated_returns = base_returns + sentiment_returns

        # Reconstruct close prices
        new_closes = np.empty(n_bars)
        new_closes[0] = closes[0]
        for i in range(1, n_bars):
            new_closes[i] = new_closes[i - 1] * (1 + modulated_returns[i - 1])
            new_closes[i] = max(new_closes[i], 0.01)  # floor

        # Scale OHLV proportionally
        scale = new_closes / np.maximum(closes, 1e-10)
        df["close"] = new_closes
        df["open"] = df["open"].values * scale
        df["high"] = df["high"].values * scale
        df["low"] = df["low"].values * scale
        # Volume stays the same (or could modulate by abs(sentiment))

        result[symbol] = df

    return result


# ---------------------------------------------------------------------------
# ScenarioBridge: orchestrates the full pipeline
# ---------------------------------------------------------------------------

class ScenarioBridge:
    """
    Generates synthetic OHLCV data from MiroFish scenarios.

    Usage:
        bridge = ScenarioBridge(client=mirofish_client)
        data = bridge.generate("fed_emergency_hike", symbols, split="val")

    Or without MiroFish (fallback mode):
        bridge = ScenarioBridge()  # no client
        data = bridge.generate("fed_emergency_hike", symbols, split="val")
    """

    def __init__(self, client=None, cache_dir=None):
        self.client = client
        self.manager = ScenarioManager(cache_dir)

    def generate(self, scenario_name, symbols=None, split="val", regenerate=False):
        """
        Generate synthetic data for a scenario.

        If cached and not regenerate, loads from cache.
        If MiroFish client is available, runs full simulation.
        Otherwise, uses fallback (expected_impact-based synthesis).

        Returns {symbol: DataFrame} in same format as prepare.load_data().
        """
        if symbols is None:
            symbols = SYMBOLS

        # Check cache first
        if not regenerate and self.manager.is_cached(scenario_name):
            return self._load_cached(scenario_name, symbols, split)

        scenario = self.manager.get_scenario(scenario_name)

        # Get sentiment trajectory
        if self.client and self.client.health_check():
            sentiment_df = self._run_mirofish(scenario)
        else:
            if self.client:
                print("  [Bridge] MiroFish not available, using fallback mode")
            sentiment_df = sentiment_from_expected_impact(scenario, scenario.rounds)

        # Load real historical data as base
        base_data = self._load_base_data(symbols, split)

        # Modulate prices
        synthetic_data = modulate_historical_prices(
            base_data, sentiment_df, scenario
        )

        # Cache results
        self._save_cached(scenario_name, synthetic_data, sentiment_df)

        return synthetic_data

    def _run_mirofish(self, scenario):
        """Run MiroFish simulation and extract sentiment trajectory."""
        sim_id, timeline, actions = self.client.run_scenario(
            name=scenario.name,
            seed_docs=scenario.seed_docs,
            agent_count=scenario.agent_count,
            rounds=scenario.rounds,
        )
        return extract_sentiment_trajectory(timeline, actions)

    def _load_base_data(self, symbols, split):
        """Load real historical data from Yahoo Finance cache."""
        splits = {
            "train": (TRAIN_START, TRAIN_END),
            "val": (VAL_START, VAL_END),
            "test": (TEST_START, TEST_END),
        }
        start_str, end_str = splits[split]
        start_ms = int(pd.Timestamp(start_str, tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end_str, tz="UTC").timestamp() * 1000)

        result = {}
        for symbol in symbols:
            filepath = os.path.join(DATA_DIR, f"{symbol}_1d.parquet")
            if not os.path.exists(filepath):
                continue
            df = pd.read_parquet(filepath)
            mask = (df["timestamp"] >= start_ms) & (df["timestamp"] < end_ms)
            split_df = df[mask].reset_index(drop=True)
            if len(split_df) > 0:
                result[symbol] = split_df
        return result

    def _save_cached(self, scenario_name, data, sentiment_df):
        """Save scenario data to cache."""
        cache_path = self.manager.get_cache_path(scenario_name)
        cache_path.mkdir(parents=True, exist_ok=True)

        for symbol, df in data.items():
            df.to_parquet(cache_path / f"{symbol}_1d.parquet", index=False)

        sentiment_df.to_parquet(cache_path / "sentiment.parquet", index=False)
        self.manager.save_metadata(scenario_name, {
            "symbols": list(data.keys()),
            "bars": {s: len(df) for s, df in data.items()},
        })

    def _load_cached(self, scenario_name, symbols, split):
        """Load cached scenario data."""
        cache_path = self.manager.get_cache_path(scenario_name)
        splits = {
            "train": (TRAIN_START, TRAIN_END),
            "val": (VAL_START, VAL_END),
            "test": (TEST_START, TEST_END),
        }
        start_str, end_str = splits[split]
        start_ms = int(pd.Timestamp(start_str, tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end_str, tz="UTC").timestamp() * 1000)

        result = {}
        for symbol in symbols:
            filepath = cache_path / f"{symbol}_1d.parquet"
            if not filepath.exists():
                continue
            df = pd.read_parquet(filepath)
            mask = (df["timestamp"] >= start_ms) & (df["timestamp"] < end_ms)
            split_df = df[mask].reset_index(drop=True)
            if len(split_df) > 0:
                result[symbol] = split_df
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate scenario data")
    parser.add_argument("scenario", help="Scenario name")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--split", default="val")
    parser.add_argument("--regenerate", action="store_true")
    parser.add_argument("--mirofish-url", default="http://localhost:5001")
    args = parser.parse_args()

    from .client import MiroFishClient
    client = MiroFishClient(base_url=args.mirofish_url)
    bridge = ScenarioBridge(client=client)

    print(f"Generating scenario: {args.scenario}")
    data = bridge.generate(args.scenario, args.symbols, args.split, args.regenerate)

    for symbol, df in data.items():
        print(f"  {symbol}: {len(df)} bars, "
              f"close range [{df['close'].min():.2f}, {df['close'].max():.2f}]")
