from __future__ import annotations

from backend.models import SignalEntry, StrategyId

ACTION_BY_TYPE: dict[str, str] = {
    "open": "buy",
    "close": "sell",
    "modify": "reduce",
}


def trade_log_to_signals(
    trade_log: list[tuple],
    strategy: StrategyId,
    equity_curve: list[float],
    initial_capital: float,
) -> list[SignalEntry]:
    """Convert run_upbit_backtest trade_log tuples into UI-facing SignalEntry list.

    trade_log tuple: (action_type, symbol, delta, exec_price, pnl, ts)
    """
    signals: list[SignalEntry] = []
    for entry in trade_log:
        action_type, symbol, delta, exec_price, pnl, ts = entry
        action = ACTION_BY_TYPE.get(action_type, "buy")
        target_fraction = abs(delta) / max(initial_capital, 1.0)
        pnl_pct = (pnl / initial_capital * 100.0) if action_type == "close" else None
        signals.append(
            SignalEntry(
                timestamp=int(ts),
                action=action,  # type: ignore[arg-type]
                symbol=symbol,
                price=float(exec_price),
                target_fraction=float(target_fraction),
                strategy=strategy,
                pnl_pct=pnl_pct,
            )
        )
    return signals


def recent_signals(
    trade_log: list[tuple],
    strategy: StrategyId,
    equity_curve: list[float],
    initial_capital: float,
    limit: int = 20,
) -> list[SignalEntry]:
    all_signals = trade_log_to_signals(trade_log, strategy, equity_curve, initial_capital)
    return all_signals[-limit:][::-1]  # newest first
