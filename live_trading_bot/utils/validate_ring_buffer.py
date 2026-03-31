"""
Validation script: Ring Buffer vs DataFrame backtest comparison.

Proves whether the _RingBuffer in backtest_interval.py produces identical
results to the old DataFrame approach, isolating the ring buffer correctness
from the lookback change (1000→500).

Runs 4 scenarios:
  1. RingBuffer + lookback=500
  2. DataFrame  + lookback=500
  3. RingBuffer + lookback=1000
  4. DataFrame  + lookback=1000

Usage: uv run validate_ring_buffer.py
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from prepare import BarData, PortfolioState

from constants import (
    BACKTEST_CAPITAL as INITIAL_CAPITAL,
    SLIPPAGE_BPS,
    TAKER_FEE,
)

# ---------------------------------------------------------------------------
# Constants (must match backtest_interval.py exactly)
# ---------------------------------------------------------------------------
MAX_LEVERAGE = 20
MINUTES_PER_YEAR = 525_600
FUNDING_BARS_MAP = {"1m": 480, "5m": 96, "15m": 32, "1h": 8}


# ---------------------------------------------------------------------------
# DataFrame-based backtest (old approach)
# ---------------------------------------------------------------------------
def run_backtest_dataframe(
    strategy, data: dict, interval: str = "15m", lookback: int = 500
) -> dict:
    """Backtest using old list-of-dicts → pd.DataFrame pattern for history."""
    t_start = time.time()
    funding_bars = FUNDING_BARS_MAP.get(interval, 480)

    all_timestamps = set()
    for symbol, df in data.items():
        all_timestamps.update(df["timestamp"].tolist())
    timestamps = sorted(all_timestamps)

    if not timestamps:
        return {"error": "no data"}

    indexed = {}
    for symbol, df in data.items():
        indexed[symbol] = df.set_index("timestamp")

    portfolio = PortfolioState(
        cash=INITIAL_CAPITAL,
        positions={},
        entry_prices={},
        equity=INITIAL_CAPITAL,
        timestamp=0,
    )

    equity_curve = [INITIAL_CAPITAL]
    returns = []
    trade_log = []
    total_volume = 0.0
    prev_equity = INITIAL_CAPITAL

    # OLD APPROACH: accumulate bar dicts into a list, trim to lookback
    history_rows = {symbol: [] for symbol in data}

    for ts in timestamps:
        portfolio.timestamp = ts

        bar_data = {}
        for symbol in data:
            if symbol not in indexed or ts not in indexed[symbol].index:
                continue
            row = indexed[symbol].loc[ts]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]

            bar_row = {
                "timestamp": ts,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "funding_rate": row.get("funding_rate", 0.0),
            }

            history_rows[symbol].append(bar_row)
            if len(history_rows[symbol]) > lookback:
                history_rows[symbol] = history_rows[symbol][-lookback:]
            hist_df = pd.DataFrame(history_rows[symbol])

            bar_data[symbol] = BarData(
                symbol=symbol,
                timestamp=ts,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                funding_rate=row.get("funding_rate", 0.0),
                history=hist_df,
            )

        if not bar_data:
            continue

        unrealized_pnl = 0.0
        for sym, pos_notional in portfolio.positions.items():
            if sym in bar_data:
                current_price = bar_data[sym].close
                entry_price = portfolio.entry_prices.get(sym, current_price)
                if entry_price > 0:
                    price_change = (current_price - entry_price) / entry_price
                    unrealized_pnl += pos_notional * price_change

        portfolio.equity = (
            portfolio.cash
            + sum(abs(v) for v in portfolio.positions.values())
            + unrealized_pnl
        )

        for sym, pos_notional in list(portfolio.positions.items()):
            if sym in bar_data:
                fr = bar_data[sym].funding_rate
                funding_payment = pos_notional * fr / funding_bars
                portfolio.cash -= funding_payment

        try:
            signals = strategy.on_bar(bar_data, portfolio)
        except Exception:
            signals = []

        for sig in signals or []:
            if sig.symbol not in bar_data:
                continue

            current_price = bar_data[sig.symbol].close
            current_pos = portfolio.positions.get(sig.symbol, 0.0)
            delta = sig.target_position - current_pos

            if abs(delta) < 1.0:
                continue

            new_positions = dict(portfolio.positions)
            new_positions[sig.symbol] = sig.target_position
            total_exposure = sum(abs(v) for v in new_positions.values())
            if total_exposure > portfolio.equity * MAX_LEVERAGE:
                continue

            slippage = current_price * SLIPPAGE_BPS / 10000
            if delta > 0:
                exec_price = current_price + slippage
            else:
                exec_price = current_price - slippage

            fee = abs(delta) * TAKER_FEE
            portfolio.cash -= fee
            total_volume += abs(delta)

            if sig.target_position == 0:
                pnl = 0
                if sig.symbol in portfolio.entry_prices:
                    entry = portfolio.entry_prices[sig.symbol]
                    if entry > 0:
                        pnl = current_pos * (exec_price - entry) / entry
                        portfolio.cash += abs(current_pos) + pnl
                    del portfolio.entry_prices[sig.symbol]
                if sig.symbol in portfolio.positions:
                    del portfolio.positions[sig.symbol]
                trade_log.append(("close", sig.symbol, delta, exec_price, pnl))
            else:
                if current_pos == 0:
                    portfolio.cash -= abs(sig.target_position)
                    portfolio.positions[sig.symbol] = sig.target_position
                    portfolio.entry_prices[sig.symbol] = exec_price
                    trade_log.append(("open", sig.symbol, delta, exec_price, 0))
                else:
                    old_notional = abs(current_pos)
                    old_entry = portfolio.entry_prices.get(sig.symbol, exec_price)
                    if abs(sig.target_position) < abs(current_pos):
                        reduced = abs(current_pos) - abs(sig.target_position)
                        pnl = 0
                        if old_entry > 0:
                            pnl = (
                                (current_pos / abs(current_pos))
                                * reduced
                                * (exec_price - old_entry)
                                / old_entry
                            )
                        portfolio.cash += reduced + pnl
                    elif abs(sig.target_position) > abs(current_pos):
                        added = abs(sig.target_position) - abs(current_pos)
                        portfolio.cash -= added
                        if old_notional + added > 0:
                            new_entry = (
                                old_entry * old_notional + exec_price * added
                            ) / (old_notional + added)
                            portfolio.entry_prices[sig.symbol] = new_entry
                    portfolio.positions[sig.symbol] = sig.target_position
                    trade_log.append(("modify", sig.symbol, delta, exec_price, 0))

        unrealized_pnl = 0.0
        for sym, pos_notional in portfolio.positions.items():
            if sym in bar_data:
                current_price = bar_data[sym].close
                entry_price = portfolio.entry_prices.get(sym, current_price)
                if entry_price > 0:
                    price_change = (current_price - entry_price) / entry_price
                    unrealized_pnl += pos_notional * price_change

        current_equity = (
            portfolio.cash
            + sum(abs(v) for v in portfolio.positions.values())
            + unrealized_pnl
        )
        equity_curve.append(current_equity)

        if prev_equity > 0:
            returns.append((current_equity - prev_equity) / prev_equity)
        prev_equity = current_equity

        if current_equity < INITIAL_CAPITAL * 0.01:
            print("  LIQUIDATED")
            break

    t_end = time.time()

    returns_arr = np.array(returns) if returns else np.array([0.0])
    eq = np.array(equity_curve)

    if returns_arr.std() > 0:
        sharpe = returns_arr.mean() / returns_arr.std()
    else:
        sharpe = 0.0

    final_equity = eq[-1] if len(eq) > 0 else INITIAL_CAPITAL
    total_return_pct = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    peak = np.maximum.accumulate(eq)
    drawdown = (peak - eq) / np.where(peak > 0, peak, 1)
    max_drawdown_pct = drawdown.max() * 100

    trade_pnls = [t[4] for t in trade_log if t[0] == "close"]
    num_trades = len(trade_log)
    num_closes = len(trade_pnls)
    if trade_pnls:
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        win_rate_pct = len(wins) / len(trade_pnls) * 100
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1e-10
        profit_factor = gross_profit / gross_loss
    else:
        win_rate_pct = 0.0
        profit_factor = 0.0

    data_minutes = len(timestamps)
    if data_minutes > 0:
        annual_turnover = total_volume * (MINUTES_PER_YEAR / data_minutes)
    else:
        annual_turnover = 0.0

    return {
        "sharpe": sharpe,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "num_trades": num_trades,
        "num_closes": num_closes,
        "win_rate_pct": win_rate_pct,
        "profit_factor": profit_factor,
        "annual_turnover": annual_turnover,
        "backtest_seconds": t_end - t_start,
        "equity_curve": equity_curve,
        "trade_log": trade_log,
        "bars_processed": len(timestamps),
        "final_equity": final_equity,
    }


# ---------------------------------------------------------------------------
# RingBuffer-based backtest (calls existing run_backtest_1m)
# ---------------------------------------------------------------------------
def run_backtest_ringbuffer(
    strategy, data: dict, interval: str = "15m", lookback: int = 500
) -> dict:
    """Run backtest using existing run_backtest_1m with monkeypatched lookback."""
    import data_pipeline.backtest.backtest_interval as bi

    # Save and restore LOOKBACK_BARS_MAP monkeypatch
    orig_lookback = bi.LOOKBACK_BARS_MAP.get(interval, 500)
    bi.LOOKBACK_BARS_MAP[interval] = lookback
    try:
        result = bi.run_backtest_1m(strategy, data, interval=interval)
    finally:
        bi.LOOKBACK_BARS_MAP[interval] = orig_lookback
    return result


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------
METRICS_TO_COMPARE = [
    "total_return_pct",
    "max_drawdown_pct",
    "num_trades",
    "num_closes",
    "win_rate_pct",
    "profit_factor",
    "sharpe",
    "annual_turnover",
    "final_equity",
]


def compare_metrics(r1: dict, r2: dict, label1: str, label2: str) -> dict:
    """Compare scalar metrics between two result dicts."""
    report = {}
    print(f"\n  Metric comparison: {label1} vs {label2}")
    print(f"  {'Metric':<22} {label1:>14} {label2:>14} {'Diff':>14} {'Status':>10}")
    print("  " + "-" * 70)
    all_match = True
    for m in METRICS_TO_COMPARE:
        v1 = r1.get(m, 0)
        v2 = r2.get(m, 0)
        diff = abs(v1 - v2)
        if m in ("num_trades", "num_closes"):
            match = diff == 0
        else:
            match = diff < 1e-10
        status = "MATCH" if match else "MISMATCH"
        if not match:
            all_match = False
        print(f"  {m:<22} {v1:>14.6f} {v2:>14.6f} {diff:>14.2e} {status:>10}")
        report[m] = {"v1": v1, "v2": v2, "diff": diff, "match": match}
    report["_all_match"] = all_match
    return report


def compare_equity_curves(r1: dict, r2: dict, label1: str, label2: str) -> dict:
    """Compare equity curves element-by-element."""
    eq1 = np.array(r1["equity_curve"])
    eq2 = np.array(r2["equity_curve"])
    report = {}
    print(f"\n  Equity curve comparison: {label1} vs {label2}")

    if len(eq1) != len(eq2):
        print(f"  LENGTH DIFFERS: {len(eq1)} vs {len(eq2)}")
        report["length_match"] = False
        report["len1"] = len(eq1)
        report["len2"] = len(eq2)
        min_len = min(len(eq1), len(eq2))
        diffs = np.abs(eq1[:min_len] - eq2[:min_len])
    else:
        report["length_match"] = True
        diffs = np.abs(eq1 - eq2)

    max_diff = diffs.max() if len(diffs) > 0 else 0
    mean_diff = diffs.mean() if len(diffs) > 0 else 0
    match = max_diff < 1e-10

    print(f"  Length: {len(eq1)} vs {len(eq2)}")
    print(f"  Max abs diff:  {max_diff:.2e}")
    print(f"  Mean abs diff: {mean_diff:.2e}")
    print(f"  Status: {'MATCH' if match else 'MISMATCH'}")

    if not match and len(diffs) > 0:
        worst_idx = np.argmax(diffs)
        print(
            f"  Worst at index {worst_idx}: {eq1[min(worst_idx, len(eq1) - 1)]:.6f} vs {eq2[min(worst_idx, len(eq2) - 1)]:.6f}"
        )
        # Show first few diffs
        nonzero = np.nonzero(diffs > 1e-12)[0]
        if len(nonzero) > 0:
            print(f"  Non-zero diff count: {len(nonzero)}")
            for idx in nonzero[:5]:
                print(
                    f"    idx={idx}: {eq1[idx]:.10f} vs {eq2[idx]:.10f} diff={diffs[idx]:.2e}"
                )
            if len(nonzero) > 5:
                print(f"    ... and {len(nonzero) - 5} more")

    report["max_diff"] = max_diff
    report["mean_diff"] = mean_diff
    report["match"] = match
    return report


def compare_trade_logs(r1: dict, r2: dict, label1: str, label2: str) -> dict:
    """Compare trade logs trade-by-trade."""
    tl1 = r1.get("trade_log", [])
    tl2 = r2.get("trade_log", [])
    report = {}
    print(f"\n  Trade log comparison: {label1} vs {label2}")

    if len(tl1) != len(tl2):
        print(f"  COUNT DIFFERS: {len(tl1)} vs {len(tl2)}")
        report["count_match"] = False
    else:
        report["count_match"] = True

    report["count1"] = len(tl1)
    report["count2"] = len(tl2)

    mismatches = []
    min_len = min(len(tl1), len(tl2))
    for i in range(min_len):
        t1 = tl1[i]
        t2 = tl2[i]
        diffs = {}
        if t1[0] != t2[0]:
            diffs["action"] = (t1[0], t2[0])
        if t1[1] != t2[1]:
            diffs["symbol"] = (t1[1], t2[1])
        if abs(t1[2] - t2[2]) > 1e-6:
            diffs["delta"] = (t1[2], t2[2])
        if abs(t1[3] - t2[3]) > 1e-10:
            diffs["price"] = (t1[3], t2[3])
        if abs(t1[4] - t2[4]) > 1e-10:
            diffs["pnl"] = (t1[4], t2[4])
        if diffs:
            mismatches.append((i, diffs))

    if mismatches:
        print(f"  MISMATCHES: {len(mismatches)} out of {min_len} trades differ")
        for idx, diffs in mismatches[:10]:
            print(f"    Trade[{idx}]:")
            for k, (v1, v2) in diffs.items():
                print(f"      {k}: {v1} vs {v2}")
        if len(mismatches) > 10:
            print(f"    ... and {len(mismatches) - 10} more mismatches")
        report["match"] = False
    else:
        if report["count_match"]:
            print(f"  All {min_len} trades MATCH exactly")
        report["match"] = report["count_match"] and len(mismatches) == 0

    report["mismatches"] = len(mismatches)
    return report


def print_summary(label: str, r: dict):
    """Print a single result row for the summary table."""
    print(
        f"  {label:<22} "
        f"Ret={r['total_return_pct']:>+8.2f}% "
        f"DD={r['max_drawdown_pct']:>6.2f}% "
        f"Trades={r['num_trades']:>5d} "
        f"Closes={r['num_closes']:>4d} "
        f"WR={r['win_rate_pct']:>5.1f}% "
        f"PF={r['profit_factor']:>6.3f} "
        f"Sh={r['sharpe']:>8.6f} "
        f"FinalEq=${r['final_equity']:>12,.2f}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import data_pipeline.backtest.backtest_interval as bi

    data_dir = str(_repo_root / "data_pipeline" / "backtest_data" / "15m_candles")
    print(f"Loading data from {data_dir}")
    data = bi.load_data(interval="15m", data_dir=data_dir)
    if not data:
        print("ERROR: No data loaded")
        sys.exit(1)

    total_bars = sum(len(df) for df in data.values())
    print(f"Loaded {total_bars} bars across {len(data)} symbols: {list(data.keys())}")
    for sym, df in data.items():
        print(f"  {sym}: {len(df)} bars")

    from live_trading_bot.strategies import strategy_15m as s15m
    from data_pipeline.backtest.tune_15m import reset_params

    reset_params()

    # ---- Run 4 scenarios ----
    scenarios = [
        ("ringbuf_500", "ringbuffer", 500),
        ("df_500", "dataframe", 500),
        ("ringbuf_1000", "ringbuffer", 1000),
        ("df_1000", "dataframe", 1000),
    ]

    results = {}
    for label, mode, lookback in scenarios:
        print(f"\n{'=' * 70}")
        print(f"Running: {label} (mode={mode}, lookback={lookback})")
        print(f"{'=' * 70}")

        reset_params()
        strategy = s15m.Strategy()

        if mode == "ringbuffer":
            r = run_backtest_ringbuffer(strategy, data, "15m", lookback)
        else:
            r = run_backtest_dataframe(strategy, data, "15m", lookback)

        if "error" in r:
            print(f"  ERROR: {r['error']}")
            results[label] = r
            continue

        print(
            f"  Bars: {r['bars_processed']}, Trades: {r['num_trades']}, "
            f"Return: {r['total_return_pct']:+.2f}%, DD: {r['max_drawdown_pct']:.2f}%"
        )
        print(f"  Final equity: ${r['final_equity']:,.2f}")
        print(f"  Time: {r['backtest_seconds']:.1f}s")
        results[label] = r

    # ---- Comparisons ----
    print(f"\n{'=' * 70}")
    print("COMPARISON 1: RingBuffer(500) vs DataFrame(500)")
    print(f"{'=' * 70}")

    if "error" not in results["ringbuf_500"] and "error" not in results["df_500"]:
        metrics_500 = compare_metrics(
            results["ringbuf_500"], results["df_500"], "ringbuf_500", "df_500"
        )
        eq_500 = compare_equity_curves(
            results["ringbuf_500"], results["df_500"], "ringbuf_500", "df_500"
        )
        trades_500 = compare_trade_logs(
            results["ringbuf_500"], results["df_500"], "ringbuf_500", "df_500"
        )
    else:
        print("  SKIPPED (one or both errored)")
        metrics_500 = {"_all_match": False}
        eq_500 = {"match": False}
        trades_500 = {"match": False}

    print(f"\n{'=' * 70}")
    print("COMPARISON 2: RingBuffer(1000) vs DataFrame(1000)")
    print(f"{'=' * 70}")

    if "error" not in results["ringbuf_1000"] and "error" not in results["df_1000"]:
        metrics_1000 = compare_metrics(
            results["ringbuf_1000"], results["df_1000"], "ringbuf_1000", "df_1000"
        )
        eq_1000 = compare_equity_curves(
            results["ringbuf_1000"], results["df_1000"], "ringbuf_1000", "df_1000"
        )
        trades_1000 = compare_trade_logs(
            results["ringbuf_1000"], results["df_1000"], "ringbuf_1000", "df_1000"
        )
    else:
        print("  SKIPPED (one or both errored)")
        metrics_1000 = {"_all_match": False}
        eq_1000 = {"match": False}
        trades_1000 = {"match": False}

    print(f"\n{'=' * 70}")
    print("COMPARISON 3: Lookback 500 vs 1000 (explaining the 404%→391% gap)")
    print(f"{'=' * 70}")

    if "error" not in results["df_500"] and "error" not in results["df_1000"]:
        compare_metrics(results["df_500"], results["df_1000"], "df_500", "df_1000")
        compare_equity_curves(
            results["df_500"], results["df_1000"], "df_500", "df_1000"
        )

    # ---- Final Summary Table ----
    print(f"\n{'=' * 70}")
    print("FINAL SUMMARY TABLE")
    print(f"{'=' * 70}")
    print()
    for label in ["ringbuf_500", "df_500", "ringbuf_1000", "df_1000"]:
        if "error" not in results[label]:
            print_summary(label, results[label])
        else:
            print(f"  {label:<22} ERROR")

    # ---- Verdict ----
    print(f"\n{'=' * 70}")
    print("VERDICT")
    print(f"{'=' * 70}")

    rb500_ok = (
        metrics_500.get("_all_match", False)
        and eq_500.get("match", False)
        and trades_500.get("match", False)
    )
    rb1000_ok = (
        metrics_1000.get("_all_match", False)
        and eq_1000.get("match", False)
        and trades_1000.get("match", False)
    )

    if rb500_ok:
        print(
            "  ✅ RingBuffer vs DataFrame at lookback=500: IDENTICAL — no ring buffer bug"
        )
    else:
        print(
            "  ❌ RingBuffer vs DataFrame at lookback=500: MISMATCH — ring buffer has a BUG!"
        )
        print("     Details above show exact discrepancies.")

    if rb1000_ok:
        print(
            "  ✅ RingBuffer vs DataFrame at lookback=1000: IDENTICAL — no ring buffer bug"
        )
    else:
        print(
            "  ❌ RingBuffer vs DataFrame at lookback=1000: MISMATCH — ring buffer has a BUG!"
        )
        print("     Details above show exact discrepancies.")

    if rb500_ok and rb1000_ok:
        ret500 = results["df_500"]["total_return_pct"]
        ret1000 = results["df_1000"]["total_return_pct"]
        diff = ret1000 - ret500
        print("\n  The 404%→391% gap is ENTIRELY from the lookback change (1000→500).")
        print(f"  DataFrame lookback=1000 return: {ret1000:+.2f}%")
        print(f"  DataFrame lookback=500  return: {ret500:+.2f}%")
        print(f"  Difference: {diff:+.2f}%")
        print("  Ring buffer implementation is CORRECT.")
    else:
        print(
            "\n  The gap has contributions from BOTH the lookback change AND a ring buffer bug."
        )
        print(
            "  Fix the ring buffer first, then re-run to isolate the lookback effect."
        )

    print()


if __name__ == "__main__":
    main()
