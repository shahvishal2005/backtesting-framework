# Tests for engine/costs.py — ticket 8
from engine.costs import (
    CostModel,
    fixed_commission,
    fixed_slippage,
    percentage_commission,
    percentage_slippage,
    zero_commission,
    zero_slippage,
)
from engine.types import Order, OrderAction


def buy_order(quantity=1):
    return Order(symbol="EURUSD", action=OrderAction.BUY, quantity=quantity)


def close_order(quantity=1):
    return Order(symbol="EURUSD", action=OrderAction.CLOSE, quantity=quantity)


def test_zero_commission_is_zero():
    assert zero_commission(buy_order(), 100.0) == 0.0


def test_zero_slippage_returns_price_unchanged():
    assert zero_slippage(buy_order(), 100.0) == 100.0


def test_cost_model_defaults_to_zero():
    model = CostModel()
    assert model.commission(buy_order(), 100.0) == 0.0
    assert model.slippage(buy_order(), 100.0) == 100.0


def test_fixed_commission_is_flat_regardless_of_size():
    commission_fn = fixed_commission(2.5)
    assert commission_fn(buy_order(quantity=1), 100.0) == 2.5
    assert commission_fn(buy_order(quantity=50), 9999.0) == 2.5


def test_percentage_commission_scales_with_notional():
    commission_fn = percentage_commission(0.01)  # 1%
    assert commission_fn(buy_order(quantity=2), 100.0) == 2.0  # 1% of 2*100


def test_fixed_slippage_moves_buy_price_up():
    slippage_fn = fixed_slippage(0.05)
    assert slippage_fn(buy_order(), 11.00) == 11.05


def test_fixed_slippage_moves_close_price_down():
    slippage_fn = fixed_slippage(0.05)
    assert slippage_fn(close_order(), 13.00) == 12.95


def test_percentage_slippage_moves_buy_price_up():
    slippage_fn = percentage_slippage(0.01)  # 1%
    assert slippage_fn(buy_order(), 100.0) == 101.0


def test_percentage_slippage_moves_close_price_down():
    slippage_fn = percentage_slippage(0.01)  # 1%
    assert slippage_fn(close_order(), 100.0) == 99.0
