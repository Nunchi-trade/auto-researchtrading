#!/usr/bin/env python3
"""Run dry-run and live bot instances side-by-side on 1m intervals, then compare signals.

Usage:
    cd live_trading_bot
    python harness/side_by_side.py --duration 5m --dry-runs 2 --live-runs 1

Requires HYPERLIQUID_PRIVATE_KEY in environment or .env file.
Each instance gets its own DB and log file in a temp directory.
After the duration, all bots are stopped and signals are compared.
"""

import argparse
import asyncio
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _stream_output(proc, prefix):
    """Read subprocess stdout line-by-line and print with prefix. Runs in a thread."""
    for line in iter(proc.stdout.readline, b""):
        text = line.decode(errors="replace").rstrip()
        if text:
            print(f"[{prefix}] {text}", flush=True)
    proc.stdout.close()


def parse_duration(s: str) -> int:
    """Parse '5m', '300s', '1h' to seconds."""
    s = s.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    elif s.endswith("h"):
        return int(s[:-1]) * 3600
    elif s.endswith("s"):
        return int(s[:-1])
    return int(s)


def extract_signals(db_path: str) -> list[dict]:
    """Extract signals from a bot's SQLite database."""
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, symbol, target_position, current_position "
        "FROM signals ORDER BY timestamp, symbol"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def extract_trades(db_path: str) -> list[dict]:
    """Extract trades from a bot's SQLite database."""
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, symbol, side, size, price "
        "FROM trades ORDER BY timestamp, symbol"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def signal_direction(target_pos: float) -> str:
    if target_pos > 1.0:
        return "LONG"
    elif target_pos < -1.0:
        return "SHORT"
    return "FLAT"


def cleanup_live_positions(db_path: str = ""):
    """Close any open positions on the exchange. Optionally log to DB."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import get_private_key
    from exchange.hyperliquid import HyperliquidClient, OrderSide, OrderType

    async def _close():
        pk = get_private_key()
        client = HyperliquidClient(private_key=pk)
        state = await client.get_account_state()

        if not state.positions:
            print("    No open positions to clean up.")
            await client.close()
            return

        conn = sqlite3.connect(db_path) if db_path else None
        for sym, pos in state.positions.items():
            side = OrderSide.SELL if pos.side.value == "long" else OrderSide.BUY
            order = await client.place_order(
                sym, side, pos.size, OrderType.MARKET, reduce_only=True
            )
            print(
                f"    Closed {sym}: {pos.size} {pos.side.value} "
                f"@ {order.avg_fill_price} ({order.status.value})"
            )
            if conn:
                conn.execute(
                    "INSERT INTO trades (timestamp, symbol, side, size, price, fee, pnl, strategy_signal, order_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, NULL, 'harness_cleanup', ?)",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        sym,
                        side.value,
                        order.filled_size,
                        order.avg_fill_price,
                        order.filled_size * 0.0005,
                        order.id,
                    ),
                )
        if conn:
            conn.commit()
            conn.close()
        await client.close()

    asyncio.run(_close())


def compare_instances(instances: list[dict]):
    """Compare signals across all instances."""
    print("\n" + "=" * 70)
    print("COMPARISON RESULTS")
    print("=" * 70)

    for inst in instances:
        signals = inst["signals"]
        trades = inst["trades"]
        mode = "DRY-RUN" if inst["dry_run"] else "LIVE"
        print(
            f"\n  {inst['name']} ({mode}): "
            f"{len(signals)} signals, {len(trades)} trades"
        )
        # Show signal breakdown by symbol
        by_symbol = defaultdict(list)
        for s in signals:
            by_symbol[s["symbol"]].append(s)
        for sym, sigs in sorted(by_symbol.items()):
            directions = [signal_direction(s["target_position"]) for s in sigs]
            print(f"    {sym}: {len(sigs)} signals — {', '.join(directions)}")

    # Pairwise agreement between all instances
    if len(instances) < 2:
        print("\nNeed at least 2 instances to compare.")
        return

    print("\n" + "-" * 70)
    print("PAIRWISE SIGNAL AGREEMENT")
    print("-" * 70)

    for i in range(len(instances)):
        for j in range(i + 1, len(instances)):
            a = instances[i]
            b = instances[j]
            _compare_pair(a, b)


def _compare_pair(a: dict, b: dict):
    a_mode = "DRY" if a["dry_run"] else "LIVE"
    b_mode = "DRY" if b["dry_run"] else "LIVE"
    print(f"\n  {a['name']}({a_mode}) vs {b['name']}({b_mode}):")

    a_sigs = a["signals"]
    b_sigs = b["signals"]

    if not a_sigs and not b_sigs:
        print("    Both produced 0 signals — nothing to compare.")
        print("    (Strategy may still be warming up. Try a longer duration.)")
        return

    if not a_sigs or not b_sigs:
        print(f"    {a['name']}: {len(a_sigs)} signals, {b['name']}: {len(b_sigs)} signals")
        print("    Cannot compare — one instance produced no signals.")
        return

    # Group by (timestamp_minute, symbol) for alignment
    def group_key(sig):
        # Round timestamp to nearest minute for alignment
        ts = sig["timestamp"]
        return (ts[:16], sig["symbol"])  # "YYYY-MM-DD HH:MM" + symbol

    a_by_key = {}
    for s in a_sigs:
        k = group_key(s)
        a_by_key[k] = s

    b_by_key = {}
    for s in b_sigs:
        k = group_key(s)
        b_by_key[k] = s

    all_keys = sorted(set(a_by_key.keys()) | set(b_by_key.keys()))
    agree = 0
    disagree = 0
    a_only = 0
    b_only = 0

    divergences = []

    for key in all_keys:
        sa = a_by_key.get(key)
        sb = b_by_key.get(key)

        if sa and sb:
            dir_a = signal_direction(sa["target_position"])
            dir_b = signal_direction(sb["target_position"])
            if dir_a == dir_b:
                agree += 1
            else:
                disagree += 1
                if len(divergences) < 5:
                    divergences.append(
                        f"    {key[0]} {key[1]}: {a['name']}={dir_a}({sa['target_position']:.0f}) "
                        f"vs {b['name']}={dir_b}({sb['target_position']:.0f})"
                    )
        elif sa:
            a_only += 1
        else:
            b_only += 1

    total = agree + disagree
    pct = (agree / total * 100) if total > 0 else 0

    print(f"    Direction agreement: {agree}/{total} ({pct:.0f}%)")
    print(f"    Signals only in {a['name']}: {a_only}")
    print(f"    Signals only in {b['name']}: {b_only}")

    if divergences:
        print(f"    First divergences:")
        for d in divergences:
            print(d)


def main():
    parser = argparse.ArgumentParser(
        description="Run dry-run and live bot instances side-by-side"
    )
    parser.add_argument(
        "--duration", default="5m", help="How long to run (e.g. 5m, 300s, 1h)"
    )
    parser.add_argument(
        "--dry-runs", type=int, default=2, help="Number of dry-run instances"
    )
    parser.add_argument(
        "--live-runs", type=int, default=1, help="Number of live instances"
    )
    parser.add_argument(
        "--interval", default="1m", help="Bar interval (default: 1m)"
    )
    args = parser.parse_args()

    duration_secs = parse_duration(args.duration)
    bot_dir = Path(__file__).resolve().parent.parent
    bot_script = bot_dir / "bot.py"

    if not bot_script.exists():
        print(f"ERROR: bot.py not found at {bot_script}")
        sys.exit(1)

    if args.live_runs > 0:
        print("Closing any leftover positions...")
        try:
            cleanup_live_positions()
        except Exception as e:
            print(f"  Warning: startup cleanup failed: {e}")
        print()

    work_dir = tempfile.mkdtemp(prefix="side_by_side_")
    print(f"Work directory: {work_dir}")
    print(f"Duration: {duration_secs}s")
    print(f"Instances: {args.dry_runs} dry-run + {args.live_runs} live")
    print(f"Interval: {args.interval}")
    print()

    instances = []
    processes = []

    for i in range(args.dry_runs + args.live_runs):
        is_dry = i < args.dry_runs
        name = f"dry_{i}" if is_dry else f"live_{i - args.dry_runs}"
        mode = "DRY-RUN" if is_dry else "LIVE"

        inst_dir = os.path.join(work_dir, name)
        os.makedirs(inst_dir, exist_ok=True)
        db_path = os.path.join(inst_dir, "bot.db")
        log_path = os.path.join(inst_dir, "bot.log")

        env = os.environ.copy()
        env["DRY_RUN"] = "true" if is_dry else "false"
        env["DB_PATH"] = db_path
        env["LOG_PATH"] = log_path
        env["BAR_INTERVAL"] = args.interval
        env["ALERT_ON_TRADE"] = "true"
        env["ALERT_INSTANCE_NAME"] = name

        print(f"  Starting {name} ({mode})...")
        proc = subprocess.Popen(
            [sys.executable, str(bot_script)],
            cwd=str(bot_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        # Stream subprocess output with instance name prefix
        t = threading.Thread(target=_stream_output, args=(proc, name), daemon=True)
        t.start()

        processes.append(proc)
        instances.append({
            "name": name,
            "dry_run": is_dry,
            "db_path": db_path,
            "log_path": log_path,
            "proc": proc,
        })

    # Handle SIGTERM (sent by Railway on redeploy) the same as KeyboardInterrupt
    _shutdown_requested = False

    def _handle_sigterm(signum, frame):
        nonlocal _shutdown_requested
        _shutdown_requested = True
        print("\nSIGTERM received, shutting down...")

    signal.signal(signal.SIGTERM, _handle_sigterm)

    print(f"\nAll instances started. Waiting {duration_secs}s...")
    print(f"(Signals may take a minute to appear after first bar completes)\n")

    try:
        for elapsed in range(duration_secs):
            if _shutdown_requested:
                break
            time.sleep(1)
            # Check if any process died early
            for inst in instances:
                rc = inst["proc"].poll()
                if rc is not None:
                    print(f"  WARNING: {inst['name']} exited early (code {rc})")
            # Progress every 30s
            if (elapsed + 1) % 30 == 0:
                mins = (elapsed + 1) // 60
                secs = (elapsed + 1) % 60
                # Count signals so far
                counts = []
                for inst in instances:
                    sigs = extract_signals(inst["db_path"])
                    trades = extract_trades(inst["db_path"])
                    last = sigs[-1]["timestamp"][11:16] if sigs else "--:--"
                    counts.append(f"{inst['name']}={len(sigs)}sig/{len(trades)}trd(last:{last})")
                print(f"  [{mins}m{secs:02d}s] {', '.join(counts)}", flush=True)
    except KeyboardInterrupt:
        print("\nInterrupted early.")

    print("\nStopping all instances...")
    for inst in instances:
        proc = inst["proc"]
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)

    # Give them time to shut down gracefully
    for inst in instances:
        try:
            inst["proc"].wait(timeout=15)
        except subprocess.TimeoutExpired:
            inst["proc"].kill()
            inst["proc"].wait()

    # Close any live positions left open and log to the live instance's DB
    live_instances = [inst for inst in instances if not inst["dry_run"]]
    if live_instances:
        print("\nCleaning up live positions...")
        for inst in live_instances:
            print(f"  {inst['name']}:")
            try:
                cleanup_live_positions(inst["db_path"])
            except Exception as e:
                print(f"    Cleanup failed: {e}")

    print("\nAll instances stopped.\n")

    # Extract signals and compare
    for inst in instances:
        inst["signals"] = extract_signals(inst["db_path"])
        inst["trades"] = extract_trades(inst["db_path"])

    compare_instances(instances)

    # Print log file locations for debugging
    print("\n" + "-" * 70)
    print("LOG FILES (for debugging):")
    for inst in instances:
        print(f"  {inst['name']}: {inst['log_path']}")
    print(f"\nWork directory: {work_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()
