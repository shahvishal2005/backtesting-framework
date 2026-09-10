# Tests for strategies/base.py and strategies/buy_and_hold.py — ticket 4
from datetime import datetime

import pytest

from engine.types import Bar, OrderAction, Position, State
from strategies.base import Strategy
from strategies.buy_and_hold import BuyAndHold


def make_bar(**overrides):
    defaults = dict(
        timestamp=datetime(2024, 1, 1),
        symbol="EURUSD",
        open=10.0,
        high=10.0,
        low=10.0,
        close=10.0,
        volume=1000.0,
    )
    defaults.update(overrides)
    return Bar(**defaults)


def make_state(bar, positions=None):
    return State(
        current_bar=bar,
        lookback=[],
        positions=positions or {},
        cash=10000.0,
        equity=10000.0,
    )


def test_strategy_is_abstract():
    with pytest.raises(TypeError):
        Strategy()


def test_concrete_subclass_can_be_instantiated():
    class NoOpStrategy(Strategy):
        def on_bar(self, bar, state):
            return []

    NoOpStrategy()  # doesn't raise


def test_buy_and_hold_buys_when_no_position():
    bar = make_bar()
    state = make_state(bar)
    orders = BuyAndHold().on_bar(bar, state)
    assert len(orders) == 1
    order = orders[0]
    assert order.symbol == "EURUSD"
    assert order.action == OrderAction.BUY
    assert order.quantity == 1


def test_buy_and_hold_holds_once_position_exists():
    bar = make_bar()
    position = Position(symbol="EURUSD", quantity=1, avg_price=10.0)
    state = make_state(bar, positions={"EURUSD": position})
    orders = BuyAndHold().on_bar(bar, state)
    assert orders == []
