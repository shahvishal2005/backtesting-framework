"""MT5 terminal -> list[Bar] historical data connector (read-only, no execution)."""

from datetime import datetime, timezone

from engine.types import Bar

# MetaTrader5's TIMEFRAME_* constant names, keyed by the short strings this module's
# callers use — kept separate from the MetaTrader5 import itself so this dict (and the
# ValueError message below) is available even where the package isn't installed.
TIMEFRAME_ATTRS = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def load_ohlcv_from_mt5(symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Bar]:
    """Connects to a running, logged-in MT5 terminal, fetches historical rates via
    MetaTrader5.copy_rates_range(), and returns Bar objects sorted by timestamp.
    Raises RuntimeError if the terminal isn't running/logged in, ValueError if the
    symbol/timeframe is unknown or the range returns no bars."""
    if timeframe not in TIMEFRAME_ATTRS:
        raise ValueError(f"unsupported timeframe {timeframe!r}; expected one of {sorted(TIMEFRAME_ATTRS)}")

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError(
            "the MetaTrader5 package is not installed — install the 'mt5' extra "
            '(pip install -e ".[mt5]"); it is Windows-only and requires a locally '
            "running, logged-in MT5 terminal"
        ) from exc

    if not mt5.initialize():
        raise RuntimeError(f"could not connect to a running MT5 terminal: {mt5.last_error()}")

    try:
        if mt5.symbol_info(symbol) is None:
            raise ValueError(f"symbol {symbol!r} is unknown to this MT5 terminal")

        mt5_timeframe = getattr(mt5, TIMEFRAME_ATTRS[timeframe])
        rates = mt5.copy_rates_range(symbol, mt5_timeframe, start, end)
        if rates is None or len(rates) == 0:
            raise ValueError(
                f"no bars returned for {symbol!r} ({timeframe}) between {start} and "
                f"{end}: {mt5.last_error()}"
            )

        bars = [
            Bar(
                timestamp=_to_naive_utc(rate["time"]),
                symbol=symbol,
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                # forex has no central real-volume figure; tick_volume (tick count) is
                # the standard proxy MT5 users rely on
                volume=float(rate["tick_volume"]),
            )
            for rate in rates
        ]
        bars.sort(key=lambda bar: bar.timestamp)
        return bars
    finally:
        mt5.shutdown()


def _to_naive_utc(epoch_seconds) -> datetime:
    """Converts MT5's epoch-seconds time field to a naive UTC datetime, matching the
    naive datetimes data/loader.py produces from CSV timestamps — mixing naive and
    timezone-aware datetimes in the same Bar stream would break sorting/comparison."""
    return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc).replace(tzinfo=None)
