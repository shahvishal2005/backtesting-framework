"""Trivial reference strategy: buy on first bar, hold."""

from engine.types import Bar, Order, OrderAction, State
from strategies.base import Strategy


class BuyAndHold(Strategy):
    """Buys 1 unit of the bar's symbol the first time it sees it, then holds indefinitely."""

    def on_bar(self, bar: Bar, state: State) -> list[Order]:
        if bar.symbol in state.positions:
            return []
        return [Order(symbol=bar.symbol, action=OrderAction.BUY, quantity=1)]
