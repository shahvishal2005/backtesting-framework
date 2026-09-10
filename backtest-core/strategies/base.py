"""Strategy interface (abstract base class)."""

from abc import ABC, abstractmethod

from engine.types import Bar, Order, State


class Strategy(ABC):
    @abstractmethod
    def on_bar(self, bar: Bar, state: State) -> list[Order]:
        """Given the current bar and account state, return zero or more orders."""
        ...
