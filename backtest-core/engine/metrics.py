"""Performance metrics: total return, Sharpe, max drawdown, win rate, profit factor."""

import math
import statistics

from engine.engine import Trade
from engine.types import OrderAction

# Convenience lookups for sharpe_ratio's annualization_factor — callers may also pass
# any other number; the function itself never assumes one (Section 7).
ANNUALIZATION_FACTORS = {
    "daily": 252,
    "hourly": 252 * 24,
    "15min": 252 * 24 * 4,
    "1min": 252 * 24 * 60,
}


def total_return(initial_equity: float, final_equity: float) -> float:
    """(final_equity / initial_equity) - 1."""
    return (final_equity / initial_equity) - 1


def sharpe_ratio(equity_curve: list[float], annualization_factor: float) -> float:
    """mean(period returns) / stdev(period returns) * sqrt(annualization_factor).
    Risk-free rate is assumed to be 0 (Phase 1). Returns 0.0 if there are fewer than
    two periods of returns, or the returns have zero variance (a flat equity curve)."""
    returns = [equity_curve[i] / equity_curve[i - 1] - 1 for i in range(1, len(equity_curve))]
    if len(returns) < 2:
        return 0.0
    stdev = statistics.stdev(returns)
    if stdev == 0:
        return 0.0
    return (statistics.mean(returns) / stdev) * math.sqrt(annualization_factor)


def max_drawdown(equity_curve: list[float]) -> float:
    """Largest peak-to-trough decline in the equity curve, as a positive fraction
    (e.g. 0.05 for a 5% drawdown). 0.0 if the curve has fewer than 2 points or never
    dips below its running peak."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def win_rate(realized_pnls: list[float]) -> float | None:
    """winning trades / total trades. None if there are no closed trades to rate."""
    if not realized_pnls:
        return None
    wins = sum(1 for pnl in realized_pnls if pnl > 0)
    return wins / len(realized_pnls)


def profit_factor(realized_pnls: list[float]) -> float | None:
    """gross profit / gross loss (absolute value). None if there's no losing trade to
    divide by — an undefined ratio, not an infinite one."""
    gross_profit = sum(pnl for pnl in realized_pnls if pnl > 0)
    gross_loss = -sum(pnl for pnl in realized_pnls if pnl < 0)
    if gross_loss == 0:
        return None
    return gross_profit / gross_loss


def realized_pnls(trades: list[Trade]) -> list[float]:
    """Pairs each CLOSE fill with the fill that opened the position and returns the
    realized P/L per completed round trip; a trailing open with no matching CLOSE
    (still open at the end of the run) contributes nothing here — it's unrealized.
    Assumes a single entry fill per round trip, true for every Phase 1 reference
    strategy (a fresh BUY followed later by one CLOSE) — adding to a position or
    partial closes are out of scope until a strategy actually needs them."""
    pnls: list[float] = []
    open_trade: Trade | None = None
    for trade in trades:
        if trade.action == OrderAction.CLOSE:
            if open_trade is not None:
                direction = 1 if open_trade.action == OrderAction.BUY else -1
                pnls.append((trade.price - open_trade.price) * trade.quantity * direction)
                open_trade = None
        else:
            open_trade = trade
    return pnls
