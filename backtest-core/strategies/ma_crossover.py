"""MA(2)/MA(4) crossover reference strategy for the known-answer test."""

from engine.types import Bar, Order, OrderAction, State
from strategies.base import Strategy

FAST_PERIOD = 2
SLOW_PERIOD = 4


class MaCrossover(Strategy):
    """Buys 1 unit when MA(2) of close crosses above MA(4); closes the position when
    it crosses back below. Computed fresh from state.lookback + the current bar on
    every call — no internal state carried on the instance."""

    def on_bar(self, bar: Bar, state: State) -> list[Order]:
        closes = [b.close for b in state.lookback] + [bar.close]
        if len(closes) < SLOW_PERIOD + 1:
            return []  # not enough history to compare today's cross to yesterday's

        today_fast = _average(closes[-FAST_PERIOD:])
        today_slow = _average(closes[-SLOW_PERIOD:])
        prior_fast = _average(closes[-FAST_PERIOD - 1 : -1])
        prior_slow = _average(closes[-SLOW_PERIOD - 1 : -1])

        crossed_up = prior_fast <= prior_slow and today_fast > today_slow
        crossed_down = prior_fast >= prior_slow and today_fast < today_slow

        has_position = bar.symbol in state.positions
        if crossed_up and not has_position:
            return [Order(symbol=bar.symbol, action=OrderAction.BUY, quantity=1)]
        if crossed_down and has_position:
            return [Order(symbol=bar.symbol, action=OrderAction.CLOSE, quantity=1)]
        return []


def _average(values: list[float]) -> float:
    return sum(values) / len(values)
