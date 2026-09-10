"""Core dataclasses: Bar, Order, Position, State."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class Bar:
    """A single OHLCV candle for one symbol at one timestamp."""

    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class OrderAction(str, Enum):
    """Action an Order instructs the engine to take."""

    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"


class OrderType(str, Enum):
    """Order fill mechanism."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


@dataclass(frozen=True)
class Order:
    """An instruction returned by a strategy; not yet a fill."""

    symbol: str
    action: OrderAction
    quantity: float              # units of the instrument (e.g. shares, lots, contracts);
                                  # Phase 1 treats this as unitless — the data layer's
                                  # symbol metadata defines what one unit means
    order_type: OrderType = OrderType.MARKET
    price: float | None = None          # required for LIMIT/STOP
    stop_loss: float | None = None
    take_profit: float | None = None
    tag: str | None = None              # free-form id for tracing fills back to signals


@dataclass
class Position:
    """An open holding in one symbol, updated by the engine as fills occur."""

    symbol: str
    quantity: float
    avg_price: float
    stop_loss: float | None = None     # carried from the Order that opened the position,
    take_profit: float | None = None   # so the engine can evaluate Section 5.1 each bar


@dataclass
class State:
    """Account and market state visible to a strategy at the current bar."""

    current_bar: Bar
    lookback: list[Bar]                 # prior bars, most recent last
    positions: dict[str, Position]
    cash: float
    equity: float
