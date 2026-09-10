"""Pluggable commission/slippage cost models, applied to fills by the engine."""

from typing import Callable

from engine.types import Order, OrderAction

# (order, raw_fill_price) -> commission charged in cash, always >= 0
CommissionFn = Callable[[Order, float], float]
# (order, raw_fill_price) -> adjusted fill price, worse for the trader than raw_fill_price
SlippageFn = Callable[[Order, float], float]


def zero_commission(order: Order, fill_price: float) -> float:
    """No commission charged."""
    return 0.0


def zero_slippage(order: Order, fill_price: float) -> float:
    """No slippage — fills exactly at the quoted price."""
    return fill_price


class CostModel:
    """Bundles a commission function and a slippage function; both default to zero,
    so an engine built without a cost model behaves exactly like tickets 5-7."""

    def __init__(
        self,
        commission: CommissionFn | None = None,
        slippage: SlippageFn | None = None,
    ):
        self.commission = commission or zero_commission
        self.slippage = slippage or zero_slippage


def fixed_commission(amount: float) -> CommissionFn:
    """A flat cash fee charged on every fill, regardless of size."""

    def commission_fn(order: Order, fill_price: float) -> float:
        return amount

    return commission_fn


def percentage_commission(rate: float) -> CommissionFn:
    """Commission proportional to the fill's notional value (rate as a fraction,
    e.g. 0.001 = 0.1%)."""

    def commission_fn(order: Order, fill_price: float) -> float:
        return rate * fill_price * order.quantity

    return commission_fn


def fixed_slippage(amount: float) -> SlippageFn:
    """Shifts the fill price by a fixed cash amount, always against the trader:
    higher on a BUY, lower on a SELL/CLOSE. Phase 1 only ever closes long positions,
    so SELL and CLOSE are treated identically here."""

    def slippage_fn(order: Order, fill_price: float) -> float:
        direction = 1 if order.action == OrderAction.BUY else -1
        return fill_price + direction * amount

    return slippage_fn


def percentage_slippage(rate: float) -> SlippageFn:
    """Shifts the fill price by a percentage of itself, always against the trader
    (rate as a fraction, e.g. 0.0005 = 0.05%)."""

    def slippage_fn(order: Order, fill_price: float) -> float:
        direction = 1 if order.action == OrderAction.BUY else -1
        return fill_price + direction * rate * fill_price

    return slippage_fn
