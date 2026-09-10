"""BacktestEngine bar-by-bar loop: immediate or next-bar-open fills, pluggable cost model."""

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime

from engine.costs import CostModel
from engine.types import Bar, Order, OrderAction, Position, State
from strategies.base import Strategy

VALID_FILL_TIMINGS = ("immediate", "next_bar_open")
VALID_INTRABAR_PATHS = ("open_high_low_close", "open_low_high_close", "pessimistic", "optimistic")


@dataclass(frozen=True)
class Trade:
    """A single executed fill, recorded to the trade log."""

    timestamp: datetime
    symbol: str
    action: OrderAction
    quantity: float
    price: float
    tag: str | None


@dataclass(frozen=True)
class EquityPoint:
    """Mark-to-market account equity at the close of one bar."""

    timestamp: datetime
    equity: float


@dataclass(frozen=True)
class RunResult:
    """Everything a single backtest run produces."""

    trades: list[Trade]
    equity_curve: list[EquityPoint]
    final_equity: float


@dataclass(frozen=True)
class SmokeTestResult:
    """Outcome of a quick pre-backtest sanity run (architecture doc Section 6)."""

    ok: bool
    error: str | None
    bars_run: int
    elapsed_seconds: float


def run_smoke_test(
    engine: "BacktestEngine",
    bars: list[Bar],
    n_bars: int = 20,
    timeout_seconds: float = 5.0,
) -> SmokeTestResult:
    """Runs engine on just the last n_bars of bars, under a wall-clock timeout,
    catching any exception the strategy raises rather than letting it propagate — a
    fast, cheap gate before committing to a full backtest. This only needs to run
    engine.run() on a slice; lookahead-bias checking (the other item the architecture
    doc's Section 6 lists) doesn't need a separate check here, since a Strategy only
    ever receives the current bar and strictly-prior bars through Section 3's
    interface — there is no path for a compliant strategy to reach future bars."""
    smoke_bars = bars[-n_bars:] if n_bars > 0 else []
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(engine.run, smoke_bars)
        try:
            future.result(timeout=timeout_seconds)
            ok, error = True, None
        except FutureTimeoutError:
            ok, error = False, f"exceeded {timeout_seconds}s timeout on {len(smoke_bars)} bars"
        except Exception as exc:  # noqa: broad on purpose — any strategy crash must be
            # reported, not raised, since the whole point is to survive arbitrary
            # strategy code without taking the caller down with it
            ok, error = False, f"{type(exc).__name__}: {exc}"

    elapsed = time.monotonic() - started
    return SmokeTestResult(ok=ok, error=error, bars_run=len(smoke_bars), elapsed_seconds=elapsed)


class BacktestEngine:
    """Runs a Strategy bar-by-bar against a list of Bar objects for one symbol."""

    def __init__(
        self,
        strategy: Strategy,
        initial_cash: float = 10000.0,
        fill_timing: str = "next_bar_open",
        cost_model: CostModel | None = None,
        intrabar_path: str = "pessimistic",
    ):
        if fill_timing not in VALID_FILL_TIMINGS:
            raise ValueError(
                f"unsupported fill_timing {fill_timing!r}; expected one of {VALID_FILL_TIMINGS}"
            )
        if intrabar_path not in VALID_INTRABAR_PATHS:
            raise ValueError(
                f"unsupported intrabar_path {intrabar_path!r}; expected one of {VALID_INTRABAR_PATHS}"
            )
        self._strategy = strategy
        self._initial_cash = initial_cash
        self._fill_timing = fill_timing
        self._cost_model = cost_model or CostModel()
        self._intrabar_path = intrabar_path

    def run(self, bars: list[Bar]) -> RunResult:
        """Runs the strategy over bars in timestamp order; returns the trade log and
        equity curve. Assumes bars are for a single symbol, already sorted (per
        data/loader.py). Market orders fill at the next bar's open by default; pass
        fill_timing="immediate" for same-bar-close fills instead."""
        positions: dict[str, Position] = {}
        cash = self._initial_cash
        lookback: list[Bar] = []
        trades: list[Trade] = []
        equity_curve: list[EquityPoint] = []
        pending_orders: list[Order] = []

        for bar in bars:
            if pending_orders:
                cash = self._fill_orders(pending_orders, bar.open, positions, cash, trades, bar.timestamp)
                pending_orders = []

            state = State(
                current_bar=bar,
                lookback=list(lookback),
                positions=dict(positions),
                cash=cash,
                equity=cash + _mark_to_market(positions, bar),
            )
            orders = self._strategy.on_bar(bar, state)

            if self._fill_timing == "immediate":
                cash = self._fill_orders(orders, bar.close, positions, cash, trades, bar.timestamp)
            else:
                pending_orders.extend(orders)

            cash = self._resolve_intrabar_exits(positions, bar, cash, trades)

            equity = cash + _mark_to_market(positions, bar)
            equity_curve.append(EquityPoint(timestamp=bar.timestamp, equity=equity))
            lookback.append(bar)

        # any orders still pending after the last bar have no next bar to fill at,
        # and are simply never filled in this run — a real data-boundary truncation,
        # not an error.
        final_equity = equity_curve[-1].equity if equity_curve else self._initial_cash
        return RunResult(trades=trades, equity_curve=equity_curve, final_equity=final_equity)

    def _fill_orders(
        self,
        orders: list[Order],
        raw_price: float,
        positions: dict[str, Position],
        cash: float,
        trades: list[Trade],
        timestamp: datetime,
    ) -> float:
        for order in orders:
            fill_price = self._cost_model.slippage(order, raw_price)
            cash = _apply_fill(positions, order, fill_price, cash)
            cash -= self._cost_model.commission(order, fill_price)
            trades.append(
                Trade(
                    timestamp=timestamp,
                    symbol=order.symbol,
                    action=order.action,
                    quantity=order.quantity,
                    price=fill_price,
                    tag=order.tag,
                )
            )
        return cash

    def _resolve_intrabar_exits(
        self,
        positions: dict[str, Position],
        bar: Bar,
        cash: float,
        trades: list[Trade],
    ) -> float:
        """Closes the bar's symbol's open position if this bar's OHLC range reaches
        its stop-loss and/or take-profit (Section 5.1). Runs once per bar, after that
        bar's own signal-driven fills, so a position opened this same bar can still be
        stopped out by the rest of this bar's range."""
        position = positions.get(bar.symbol)
        if position is None or (position.stop_loss is None and position.take_profit is None):
            return cash

        outcome = _resolve_intrabar_exit(position, bar, self._intrabar_path)
        if outcome is None:
            return cash

        trigger_type, raw_price = outcome
        order = Order(
            symbol=bar.symbol,
            action=OrderAction.CLOSE,
            quantity=abs(position.quantity),
            tag=trigger_type,
        )
        return self._fill_orders([order], raw_price, positions, cash, trades, bar.timestamp)


def _resolve_intrabar_exit(
    position: Position, bar: Bar, intrabar_path: str
) -> tuple[str, float] | None:
    """Returns (trigger_type, raw_price) if this bar's range reaches the position's
    stop-loss and/or take-profit, else None. When both are reached, resolves the
    ambiguity by walking the configured intrabar_path and returning whichever level
    it reaches first (Section 5.1)."""
    sl = position.stop_loss
    tp = position.take_profit
    is_long = position.quantity > 0

    sl_hit = sl is not None and ((is_long and bar.low <= sl) or (not is_long and bar.high >= sl))
    tp_hit = tp is not None and ((is_long and bar.high >= tp) or (not is_long and bar.low <= tp))

    if not sl_hit and not tp_hit:
        return None
    if sl_hit and not tp_hit:
        return ("stop_loss", sl)
    if tp_hit and not sl_hit:
        return ("take_profit", tp)

    # both reached this bar — the ambiguous case Section 5.1 exists to resolve
    path = _concrete_path(intrabar_path, is_long)
    high_side_first = path == "open_high_low_close"
    # for a long, the high side is the take-profit side; for a short, it's the stop side
    if high_side_first:
        return ("take_profit", tp) if is_long else ("stop_loss", sl)
    return ("stop_loss", sl) if is_long else ("take_profit", tp)


def _concrete_path(intrabar_path: str, is_long: bool) -> str:
    """Maps pessimistic/optimistic to a concrete open->high/low path, direction-aware:
    pessimistic always resolves toward the stop-loss side first, regardless of
    long/short, so it never overstates performance."""
    if intrabar_path in ("open_high_low_close", "open_low_high_close"):
        return intrabar_path
    stop_side_path = "open_low_high_close" if is_long else "open_high_low_close"
    target_side_path = "open_high_low_close" if is_long else "open_low_high_close"
    return stop_side_path if intrabar_path == "pessimistic" else target_side_path


def _mark_to_market(positions: dict[str, Position], bar: Bar) -> float:
    """Value of open positions at this bar's close. Phase 1 runs one symbol per
    engine.run() call, so only positions[bar.symbol] can move today; any other symbol
    (out of scope until multi-symbol support exists) is valued at its last known
    average price."""
    total = 0.0
    for symbol, position in positions.items():
        price = bar.close if symbol == bar.symbol else position.avg_price
        total += position.quantity * price
    return total


def _apply_fill(
    positions: dict[str, Position], order: Order, fill_price: float, cash: float
) -> float:
    """Applies one order's fill to positions (in place) and returns updated cash.
    Always replaces positions[symbol] with a new Position rather than mutating an
    existing one, so a Position object already handed to a strategy via an earlier
    State never changes out from under it."""
    existing = positions.get(order.symbol)

    if order.action == OrderAction.CLOSE:
        if existing is None:
            return cash  # nothing open to close — a defensive close-if-open is a no-op
        cash += existing.quantity * fill_price
        del positions[order.symbol]
        return cash

    signed_quantity = order.quantity if order.action == OrderAction.BUY else -order.quantity
    cash -= signed_quantity * fill_price

    if existing is None:
        positions[order.symbol] = Position(
            symbol=order.symbol,
            quantity=signed_quantity,
            avg_price=fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
        )
        return cash

    new_quantity = existing.quantity + signed_quantity
    if new_quantity == 0:
        del positions[order.symbol]
        return cash

    total_cost = existing.avg_price * existing.quantity + fill_price * signed_quantity
    positions[order.symbol] = Position(
        symbol=order.symbol,
        quantity=new_quantity,
        avg_price=total_cost / new_quantity,
        stop_loss=existing.stop_loss,
        take_profit=existing.take_profit,
    )
    return cash
