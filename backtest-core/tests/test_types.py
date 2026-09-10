# Tests for engine/types.py — ticket 2
import dataclasses
from datetime import datetime

import pytest

from engine.types import Bar, Order, OrderAction, OrderType, Position, State


def make_bar(**overrides):
    defaults = dict(
        timestamp=datetime(2024, 1, 1),
        symbol="EURUSD",
        open=1.10,
        high=1.11,
        low=1.09,
        close=1.105,
        volume=1000.0,
    )
    defaults.update(overrides)
    return Bar(**defaults)


def test_bar_construction():
    bar = make_bar()
    assert bar.symbol == "EURUSD"
    assert bar.open == 1.10
    assert bar.high == 1.11
    assert bar.low == 1.09
    assert bar.close == 1.105
    assert bar.volume == 1000.0


def test_bar_is_frozen():
    bar = make_bar()
    with pytest.raises(dataclasses.FrozenInstanceError):
        bar.close = 2.0


def test_order_defaults():
    order = Order(symbol="EURUSD", action=OrderAction.BUY, quantity=1)
    assert order.order_type == OrderType.MARKET
    assert order.price is None
    assert order.stop_loss is None
    assert order.take_profit is None
    assert order.tag is None


def test_order_explicit_fields():
    order = Order(
        symbol="EURUSD",
        action=OrderAction.SELL,
        quantity=2,
        order_type=OrderType.LIMIT,
        price=1.10,
        stop_loss=1.12,
        take_profit=1.05,
        tag="signal-1",
    )
    assert order.order_type == OrderType.LIMIT
    assert order.price == 1.10
    assert order.stop_loss == 1.12
    assert order.take_profit == 1.05
    assert order.tag == "signal-1"


def test_order_is_frozen():
    order = Order(symbol="EURUSD", action=OrderAction.BUY, quantity=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        order.quantity = 5


def test_order_action_is_str_enum():
    # str subclass so ticket 11's JSON output serializes as plain "BUY", not an enum repr
    assert OrderAction.BUY == "BUY"
    assert isinstance(OrderAction.BUY, str)


def test_order_type_is_str_enum():
    assert OrderType.MARKET == "MARKET"
    assert isinstance(OrderType.MARKET, str)


def test_position_construction_and_defaults():
    position = Position(symbol="EURUSD", quantity=1, avg_price=1.10)
    assert position.stop_loss is None
    assert position.take_profit is None


def test_position_is_mutable():
    # engine updates positions in place every bar — must not be frozen
    position = Position(symbol="EURUSD", quantity=1, avg_price=1.10)
    position.quantity = 2
    position.avg_price = 1.12
    assert position.quantity == 2
    assert position.avg_price == 1.12


def test_state_construction():
    bar = make_bar()
    state = State(
        current_bar=bar,
        lookback=[],
        positions={},
        cash=10000.0,
        equity=10000.0,
    )
    assert state.current_bar is bar
    assert state.lookback == []
    assert state.positions == {}
    assert state.cash == 10000.0
    assert state.equity == 10000.0


def test_state_is_mutable():
    bar = make_bar()
    state = State(current_bar=bar, lookback=[], positions={}, cash=10000.0, equity=10000.0)
    state.cash -= 100.0
    state.equity -= 100.0
    assert state.cash == 9900.0
    assert state.equity == 9900.0


def test_state_positions_hold_multiple_symbols():
    bar = make_bar()
    positions = {
        "EURUSD": Position(symbol="EURUSD", quantity=1, avg_price=1.10),
        "GBPUSD": Position(symbol="GBPUSD", quantity=1, avg_price=1.25),
    }
    state = State(current_bar=bar, lookback=[], positions=positions, cash=10000.0, equity=10000.0)
    assert set(state.positions.keys()) == {"EURUSD", "GBPUSD"}
