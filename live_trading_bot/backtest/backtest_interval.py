"""
Interval backtest: downloads candles from Hyperliquid at any supported interval,
runs the current strategy through a backtest engine.

Usage: uv run backtest_interval.py [--interval 1m|5m|15m|1h] [--data-dir DIR] [--download]

Defaults to loading from backtest_data/{interval}_candles/.
Use --download to fetch fresh data from Hyperliquid instead.
"""

import os
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

_repo_root = Path(__file__).resolve().parent.parent.parent
_bot_root = Path(__file__).resolve().parent.parent
for _p in (_bot_root, _repo_root):
    sp = str(_p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
import requests

from prepare import BarData, Signal, PortfolioState

INITIAL_CAPITAL = 10_000.0
TAKER_FEE = 0.0005
SLIPPAGE_BPS = 1.0
MAX_LEVERAGE = 20
MINUTES_PER_YEAR = 525_600

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
VALID_INTERVALS = list(INTERVAL_MINUTES.keys())

LOOKBACK_BARS_MAP = {"1m": 1500, "5m": 1500, "15m": 1000, "1h": 500}
FUNDING_BARS_MAP = {
    "1m": 480,  # 8h * 60min
    "5m": 96,  # 8h * 60 / 5
    "15m": 32,  # 8h * 60 / 15
    "1h": 8,  # 8h * 60 / 60
}

SYMBOLS = ["BTC", "ETH", "SOL", "XRP"]
HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def default_data_dir(interval: str = "1m") -> str:
    return os.path.join(_bot_root, "backtest_data", f"{interval}_candles")


def cache_data_dir(interval: str = "1m") -> str:
    return os.path.join(
        os.path.expanduser("~"), ".cache", "autotrader", f"data_{interval}"
    )


def download_candles(
    symbol: str, start_ms: int, end_ms: int, interval: str = "1m"
) -> pd.DataFrame:
    """Download OHLCV candles from Hyperliquid with automatic pagination (max 5000 per request)."""
    interval_minutes = INTERVAL_MINUTES.get(interval, 1)
    # 5000 bars in ms = 5000 * interval_minutes * 60 * 1000
    chunk_ms = 5000 * interval_minutes * 60 * 1000
    all_rows = []
    current = start_ms

    while current < end_ms:
        chunk_end = min(current + chunk_ms, end_ms)
        body = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": current,
                "endTime": chunk_end,
            },
        }
        try:
            resp = requests.post(HL_INFO_URL, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                break

            for row in data:
                all_rows.append(
                    {
                        "timestamp": int(row["t"]),
                        "open": float(row["o"]),
                        "high": float(row["h"]),
                        "low": float(row["l"]),
                        "close": float(row["c"]),
                        "volume": float(row["v"]),
                    }
                )

            # Advance past the last received candle
            current = int(data[-1]["t"]) + interval_minutes * 60 * 1000
            time.sleep(0.15)
        except Exception as e:
            print(f"    Warning: candle fetch failed for {symbol}: {e}")
            break

    if not all_rows:
        return pd.DataFrame()

    df = (
        pd.DataFrame(all_rows)
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
        .reset_index(drop=True)
    )
    return df


def download_funding_rates(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Download funding rate history from Hyperliquid."""
    all_rows = []
    current = start_ms
    while current < end_ms:
        body = {
            "type": "fundingHistory",
            "coin": symbol,
            "startTime": current,
            "endTime": min(current + 30 * 24 * 3600 * 1000, end_ms),
        }
        try:
            resp = requests.post(HL_INFO_URL, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            for row in data:
                all_rows.append(
                    {
                        "timestamp": int(row["time"]),
                        "funding_rate": float(row["fundingRate"]),
                    }
                )
            current = int(data[-1]["time"]) + 1
        except Exception as e:
            print(f"  Warning: funding fetch failed for {symbol}: {e}")
            break
        time.sleep(0.2)

    if not all_rows:
        return pd.DataFrame(columns=pd.Index(["timestamp", "funding_rate"]))
    return pd.DataFrame(all_rows)


def download_all_data(hours_back: int = 24, interval: str = "1m"):
    """Download candles + funding for all symbols, save to cache, return loaded data."""
    cache_dir = cache_data_dir(interval)
    os.makedirs(cache_dir, exist_ok=True)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (hours_back * 3600 * 1000)

    for symbol in SYMBOLS:
        filepath = os.path.join(cache_dir, f"{symbol}_{interval}.parquet")
        if os.path.exists(filepath):
            existing = pd.read_parquet(filepath)
            newest = existing["timestamp"].max()
            if (end_ms - newest) < 3600 * 1000:
                print(f"  {symbol}: using cached {len(existing)} bars (fresh)")
                continue

        print(f"  {symbol}: downloading {hours_back}h of {interval} candles...")
        df = download_candles(symbol, start_ms, end_ms, interval)

        if df.empty:
            print(f"  {symbol}: NO DATA AVAILABLE, skipping")
            continue

        print(f"  {symbol}: downloading funding rates...")
        funding = download_funding_rates(symbol, start_ms, end_ms)

        if not funding.empty:
            funding = funding.drop_duplicates(subset=["timestamp"]).sort_values(
                "timestamp"
            )
            df = pd.merge_asof(df, funding, on="timestamp", direction="backward")
        if "funding_rate" not in df.columns:
            df["funding_rate"] = 0.0
        df["funding_rate"] = df["funding_rate"].fillna(0.0)

        df.to_parquet(filepath, index=False)
        print(f"  {symbol}: saved {len(df)} bars to {filepath}")

    return load_data(interval=interval, data_dir=cache_dir)


def load_data(interval: str = "1m", data_dir: str | None = None) -> dict:
    """Load parquet data from data_dir for the given interval. Returns {symbol: DataFrame}."""
    if data_dir is None:
        data_dir = default_data_dir(interval)
    result = {}
    for symbol in SYMBOLS:
        filepath = os.path.join(data_dir, f"{symbol}_{interval}.parquet")
        if not os.path.exists(filepath):
            print(f"  Warning: no data for {symbol} at {filepath}")
            continue
        df = pd.read_parquet(filepath)
        if len(df) > 0:
            result[symbol] = df
    return result


def run_backtest_1m(strategy, data: dict, interval: str = "1m") -> dict:
    """Run strategy over data with interval-aware Sharpe/funding scaling."""
    t_start = time.time()
    lookback = LOOKBACK_BARS_MAP.get(interval, 1500)
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
    history_buffers = {symbol: [] for symbol in data}

    for ts in timestamps:
        portfolio.timestamp = ts

        bar_data = {}
        for symbol in data:
            if symbol not in indexed or ts not in indexed[symbol].index:
                continue
            row = indexed[symbol].loc[ts]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]

            bar_dict = {
                "timestamp": ts,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "funding_rate": row.get("funding_rate", 0.0),
            }
            history_buffers[symbol].append(bar_dict)
            if len(history_buffers[symbol]) > lookback:
                history_buffers[symbol] = history_buffers[symbol][-lookback:]

            hist_df = pd.DataFrame(history_buffers[symbol])

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


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Interval Backtest")
    parser.add_argument(
        "--interval",
        choices=VALID_INTERVALS,
        default="1m",
        help="Candle interval (default: 1m)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory with parquet files (default: backtest_data/{interval}_candles/)",
    )
    parser.add_argument(
        "--strategy",
        default="strategies.strategy_1m",
        help="Strategy module to import (default: strategies.strategy_1m)",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download fresh data from Hyperliquid instead of loading files",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours of data to download (only with --download)",
    )
    args = parser.parse_args()

    interval = args.interval

    print("=" * 60)
    print(f"Interval Backtest ({interval})")
    print("=" * 60)

    if args.download:
        print(f"\nDownloading {args.hours}h of {interval} data...")
        data = download_all_data(hours_back=args.hours, interval=interval)
    else:
        data_dir = args.data_dir or default_data_dir(interval)
        print(f"\nLoading data from {data_dir} ...")
        data = load_data(interval=interval, data_dir=args.data_dir)

    if not data:
        print("ERROR: No data available")
        sys.exit(1)

    total_bars = sum(len(df) for df in data.values())
    print(f"\nLoaded {total_bars} bars across {len(data)} symbols: {list(data.keys())}")

    all_ts = []
    for df in data.values():
        all_ts.extend(df["timestamp"].tolist())
    all_ts.sort()
    first_t = pd.Timestamp(all_ts[0], unit="ms", tz="UTC")
    last_t = pd.Timestamp(all_ts[-1], unit="ms", tz="UTC")
    print(f"Time range: {first_t} to {last_t}")
    print(f"Duration: {(all_ts[-1] - all_ts[0]) / 3600_000:.1f} hours")

    import importlib

    mod = importlib.import_module(args.strategy)
    strategy = mod.Strategy()

    print(f"\nStrategy: {args.strategy}")

    print("\nRunning backtest...")
    result = run_backtest_1m(strategy, data, interval=interval)

    print("\n" + "-" * 60)
    print("RESULTS")
    print("-" * 60)
    print(f"  interval:          {interval}")
    print(f"  bars_processed:    {result['bars_processed']}")
    print(f"  num_trades:        {result['num_trades']}")
    print(f"  num_closes:        {result['num_closes']}")
    print(
        f"  per_bar_sharpe:    {result['sharpe']:.6f}  (not annualized — sample too small)"
    )
    print(f"  total_return_pct:  {result['total_return_pct']:.4f}%")
    print(f"  max_drawdown_pct:  {result['max_drawdown_pct']:.4f}%")
    print(f"  win_rate_pct:      {result['win_rate_pct']:.1f}%")
    print(f"  profit_factor:     {result['profit_factor']:.4f}")
    print(f"  annual_turnover:   ${result['annual_turnover']:,.0f}")
    print(f"  final_equity:      ${result['final_equity']:,.2f}")
    print(f"  backtest_seconds:  {result['backtest_seconds']:.1f}s")

    if result["trade_log"]:
        closes = [t for t in result["trade_log"] if t[0] == "close"]
        print(f"\n  Trade summary:")
        print(f"    opens:  {len([t for t in result['trade_log'] if t[0] == 'open'])}")
        print(f"    closes: {len(closes)}")
        if closes:
            pnls = [t[4] for t in closes]
            print(f"    total PnL: ${sum(pnls):,.2f}")
            print(f"    avg PnL:   ${np.mean(pnls):,.2f}")
            print(f"    best PnL:  ${max(pnls):,.2f}")
            print(f"    worst PnL: ${min(pnls):,.2f}")

    if result["trade_log"]:
        print(f"\n  Last 10 trades:")
        for t in result["trade_log"][-10:]:
            action, symbol, delta, price, pnl = t
            pnl_str = f"${pnl:,.2f}" if action == "close" else ""
            print(
                f"    {action:6s} {symbol:4s} delta={delta:>10.1f} price={price:>10.2f} {pnl_str}"
            )

    eq = result["equity_curve"]
    if len(eq) > 1:
        n = len(eq)
        print(f"\n  Equity curve (sampled):")
        for pct in [0, 25, 50, 75, 100]:
            idx = min(int(n * pct / 100), n - 1)
            print(f"    {pct:3d}%: ${eq[idx]:>12,.2f}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
