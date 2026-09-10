# Known-answer test: intrabar path resolution (SL/TP ordering) — ticket 9
from datetime import datetime

import pytest

from engine.engine import BacktestEngine
from engine.types import Bar, Order, OrderAction, State
from strategies.base import Strategy

ENTRY_PRICE = 100.0
STOP_LOSS = 95.0
TAKE_PROFIT = 108.0


class _OpenWithStopsStrategy(Strategy):
    """Buys once with a fixed SL/TP, then holds — used only by this test."""

    def __init__(self, stop_loss: float, take_profit: float):
        self._stop_loss = stop_loss
        self._take_profit = take_profit

    def on_bar(self, bar: Bar, state: State) -> list[Order]:
        if bar.symbol in state.positions:
            return []
        return [
            Order(
                symbol=bar.symbol,
                action=OrderAction.BUY,
                quantity=1,
                stop_loss=self._stop_loss,
                take_profit=self._take_profit,
            )
        ]


def make_bar(timestamp, open, high, low, close):
    return Bar(
        timestamp=timestamp,
        symbol="EURUSD",
        open=open,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
    )


def run_with_path(intrabar_path: str, ambiguous_bar: Bar):
    entry_bar = make_bar(datetime(2024, 1, 1), ENTRY_PRICE, ENTRY_PRICE, ENTRY_PRICE, ENTRY_PRICE)
    strategy = _OpenWithStopsStrategy(stop_loss=STOP_LOSS, take_profit=TAKE_PROFIT)
    engine = BacktestEngine(
        strategy, initial_cash=10000.0, fill_timing="immediate", intrabar_path=intrabar_path
    )
    return engine.run([entry_bar, ambiguous_bar])


# Section 6.1's bar: open=100, high=110, low=90, close=105 — reaches both the 95 stop
# and the 108 target, so the outcome depends entirely on the path assumption.
AMBIGUOUS_BAR = make_bar(datetime(2024, 1, 2), open=100.0, high=110.0, low=90.0, close=105.0)


def test_open_high_low_close_hits_take_profit_first():
    result = run_with_path("open_high_low_close", AMBIGUOUS_BAR)
    exit_trade = result.trades[-1]
    assert exit_trade.price == 108.0
    assert result.final_equity - 10000.0 == pytest.approx(8.00)


def test_open_low_high_close_hits_stop_loss_first():
    result = run_with_path("open_low_high_close", AMBIGUOUS_BAR)
    exit_trade = result.trades[-1]
    assert exit_trade.price == 95.0
    assert result.final_equity - 10000.0 == pytest.approx(-5.00)


def test_pessimistic_default_matches_open_low_high_close_for_long():
    result = run_with_path("pessimistic", AMBIGUOUS_BAR)
    exit_trade = result.trades[-1]
    assert exit_trade.price == 95.0
    assert result.final_equity - 10000.0 == pytest.approx(-5.00)


def test_optimistic_matches_open_high_low_close_for_long():
    # not in Section 6.1's table, but the fourth valid intrabar_path value — for a
    # long position it should alias to open_high_low_close (best case: TP first)
    result = run_with_path("optimistic", AMBIGUOUS_BAR)
    exit_trade = result.trades[-1]
    assert exit_trade.price == 108.0
    assert result.final_equity - 10000.0 == pytest.approx(8.00)


def test_only_take_profit_reached_closes_at_take_profit_regardless_of_path():
    only_tp_bar = make_bar(datetime(2024, 1, 2), open=100.0, high=109.0, low=99.0, close=105.0)
    for path in ("open_high_low_close", "open_low_high_close", "pessimistic", "optimistic"):
        result = run_with_path(path, only_tp_bar)
        exit_trade = result.trades[-1]
        assert exit_trade.price == 108.0
        assert result.final_equity - 10000.0 == pytest.approx(8.00)


def test_neither_level_reached_position_stays_open():
    narrow_bar = make_bar(datetime(2024, 1, 2), open=100.0, high=102.0, low=98.0, close=101.0)
    result = run_with_path("pessimistic", narrow_bar)
    assert len(result.trades) == 1  # only the entry — no exit triggered
    assert result.final_equity == pytest.approx(10000.0 + (101.0 - ENTRY_PRICE))
