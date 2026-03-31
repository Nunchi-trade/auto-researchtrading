"""Quick validation: compare BPP=2.0 (broken) vs BPP=0.08 (fixed) returns."""

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from data_pipeline.backtest.backtest_interval import load_data, run_backtest_1m
from live_trading_bot.strategies import strategy_15m as s15m
import pandas as pd

data = load_data(
    interval="15m",
    data_dir=str(_repo_root / "data_pipeline" / "backtest_data" / "15m_candles"),
)
print(f"Bars: {sum(len(df) for df in data.values())}")

# --- Market movement ---
print("\n=== UNDERLYING MARKET MOVEMENT ===")
for sym in sorted(data):
    df = data[sym]
    first = df["close"].iloc[0]
    last = df["close"].iloc[-1]
    pct = (last - first) / first * 100
    t0 = pd.Timestamp(df["timestamp"].iloc[0], unit="ms", tz="UTC")
    t1 = pd.Timestamp(df["timestamp"].iloc[-1], unit="ms", tz="UTC")
    print(
        f"  {sym}: ${first:,.2f} -> ${last:,.2f} ({pct:+.1f}%)  {t0.date()} to {t1.date()}"
    )

# --- BROKEN: BPP=2.0 ---
print("\n=== BROKEN (BPP=2.0, old tune default) ===")
for k, v in dict(
    BASE_POSITION_PCT=2.0,
    SHORT_WINDOW=24,
    MED_WINDOW=48,
    RSI_PERIOD=32,
    COOLDOWN_BARS=8,
    MIN_VOTES=4,
    BASE_THRESHOLD=0.012,
    ATR_STOP_MULT=5.5,
).items():
    setattr(s15m, k, v)
strategy = s15m.Strategy()
r = run_backtest_1m(strategy, data, "15m")
print(
    f"  Return: {r['total_return_pct']:+.2f}%  DD: {r['max_drawdown_pct']:.2f}%  PF: {r['profit_factor']:.2f}  WR: {r['win_rate_pct']:.1f}%  Trades: {r['num_trades']}  Equity: ${r['final_equity']:,.2f}"
)
exposure = 10000 * 2.0 * 0.25 * 4
print(f"  Total exposure at $10k: ${exposure:,.0f} ({exposure / 10000:.0f}x leverage)")

# --- FIXED: BPP=0.08 ---
print("\n=== FIXED (BPP=0.08, production value) ===")
setattr(s15m, "BASE_POSITION_PCT", 0.08)
strategy = s15m.Strategy()
r2 = run_backtest_1m(strategy, data, "15m")
print(
    f"  Return: {r2['total_return_pct']:+.2f}%  DD: {r2['max_drawdown_pct']:.2f}%  PF: {r2['profit_factor']:.2f}  WR: {r2['win_rate_pct']:.1f}%  Trades: {r2['num_trades']}  Equity: ${r2['final_equity']:,.2f}"
)
exposure2 = 10000 * 0.08 * 0.25 * 4
print(
    f"  Total exposure at $10k: ${exposure2:,.0f} ({exposure2 / 10000:.2f}x leverage)"
)

# --- STEPWISE RECOMMENDED ---
print("\n=== STEPWISE RECOMMENDED (from pipeline fix) ===")
stepwise = dict(
    BASE_POSITION_PCT=0.1,
    RSI_PERIOD=28,
    COOLDOWN_BARS=20,
    VOL_LOOKBACK=96,
    EMA_FAST=36,
    EMA_SLOW=140,
)
for k, v in stepwise.items():
    setattr(s15m, k, v)
# reset others to defaults
for k2, v2 in dict(
    SHORT_WINDOW=24, MED_WINDOW=48, MIN_VOTES=4, BASE_THRESHOLD=0.012, ATR_STOP_MULT=5.5
).items():
    setattr(s15m, k2, v2)
strategy = s15m.Strategy()
r3 = run_backtest_1m(strategy, data, "15m")
print(f"  Params: {stepwise}")
print(
    f"  Return: {r3['total_return_pct']:+.2f}%  DD: {r3['max_drawdown_pct']:.2f}%  PF: {r3['profit_factor']:.2f}  WR: {r3['win_rate_pct']:.1f}%  Trades: {r3['num_trades']}  Equity: ${r3['final_equity']:,.2f}"
)

# --- OOS VALIDATION ---
print("\n=== OOS VALIDATION (stepwise params, 60/40 split) ===")
all_ts = sorted(set(t for df in data.values() for t in df["timestamp"].tolist()))
split_ts = all_ts[int(len(all_ts) * 0.6)]
train = {s: df[df["timestamp"] <= split_ts].copy() for s, df in data.items()}
oos = {s: df[df["timestamp"] > split_ts].copy() for s, df in data.items()}
train_bars = sum(len(df) for df in train.values())
oos_bars = sum(len(df) for df in oos.values())
t0 = pd.Timestamp(all_ts[0], unit="ms", tz="UTC")
ts = pd.Timestamp(split_ts, unit="ms", tz="UTC")
t1 = pd.Timestamp(all_ts[-1], unit="ms", tz="UTC")
print(f"  Train: {t0.date()} -> {ts.date()} ({train_bars} bars)")
print(f"  OOS:   {ts.date()} -> {t1.date()} ({oos_bars} bars)")

# IS
for k, v in stepwise.items():
    setattr(s15m, k, v)
for k2, v2 in dict(
    SHORT_WINDOW=24, MED_WINDOW=48, MIN_VOTES=4, BASE_THRESHOLD=0.012, ATR_STOP_MULT=5.5
).items():
    setattr(s15m, k2, v2)
is_r = run_backtest_1m(s15m.Strategy(), train, "15m")

# OOS
for k, v in stepwise.items():
    setattr(s15m, k, v)
for k2, v2 in dict(
    SHORT_WINDOW=24, MED_WINDOW=48, MIN_VOTES=4, BASE_THRESHOLD=0.012, ATR_STOP_MULT=5.5
).items():
    setattr(s15m, k2, v2)
oos_r = run_backtest_1m(s15m.Strategy(), oos, "15m")


# Score
def score(r):
    ret = r["total_return_pct"]
    dd = max(r["max_drawdown_pct"], 0.01)
    bpp = r.get("params", {}).get("BASE_POSITION_PCT", 0.1)
    norm_ret = ret / max(bpp, 0.1)
    nc = r.get("num_closes", r.get("num_trades", 0))
    tc = min(nc / 20.0, 1.0)
    pf = r.get("profit_factor", 1.0)
    pf_b = 1.0 + max(0, pf - 2) * 0.1
    return norm_ret / dd * tc * pf_b


is_s = score(is_r)
oos_s = score(oos_r)
deg = (is_s - oos_s) / is_s if is_s > 0 else float("inf")
verdict = "PASS" if deg < 0.3 else ("CAUTION" if deg < 0.6 else "FAIL")

print(
    f"  IS  Return={is_r['total_return_pct']:+.2f}%  DD={is_r['max_drawdown_pct']:.2f}%  PF={is_r['profit_factor']:.2f}  WR={is_r['win_rate_pct']:.1f}%  Trades={is_r['num_trades']}  Score={is_s:.2f}"
)
print(
    f"  OOS Return={oos_r['total_return_pct']:+.2f}%  DD={oos_r['max_drawdown_pct']:.2f}%  PF={oos_r['profit_factor']:.2f}  WR={oos_r['win_rate_pct']:.1f}%  Trades={oos_r['num_trades']}  Score={oos_s:.2f}"
)
print(f"  Degradation: {deg * 100:.1f}% -> {verdict}")

# --- COMPARISON ---
print("\n=== COMPARISON ===")
print(
    f"  BPP=2.0 (broken):  Return={r['total_return_pct']:+.2f}%  Equity=${r['final_equity']:,.2f}"
)
print(
    f"  BPP=0.08 (fixed):  Return={r2['total_return_pct']:+.2f}%  Equity=${r2['final_equity']:,.2f}"
)
print(
    f"  Stepwise (tuned):   Return={r3['total_return_pct']:+.2f}%  Equity=${r3['final_equity']:,.2f}"
)
if abs(r2["total_return_pct"]) > 0.01:
    print(
        f"  Inflation ratio (broken/fixed): {r['total_return_pct'] / r2['total_return_pct']:.1f}x"
    )
print(
    f"  Same trades? {r['num_trades'] == r2['num_trades']}  Same WR? {abs(r['win_rate_pct'] - r2['win_rate_pct']) < 0.1}"
)
