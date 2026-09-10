# Tests for data/mt5_loader.py (mocked MT5 API) and the mt5-fetch CLI — ticket 13
import sys
from datetime import datetime, timezone

import numpy as np
import pytest
from click.testing import CliRunner

from cli import mt5_fetch
from data.mt5_loader import load_ohlcv_from_mt5

RATE_DTYPE = [
    ("time", "i8"),
    ("open", "f8"),
    ("high", "f8"),
    ("low", "f8"),
    ("close", "f8"),
    ("tick_volume", "i8"),
    ("spread", "i4"),
    ("real_volume", "i8"),
]


def epoch(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def make_rates(rows):
    return np.array(rows, dtype=RATE_DTYPE)


class FakeMt5:
    """Stand-in for the MetaTrader5 module — only the calls mt5_loader.py uses."""

    TIMEFRAME_D1 = 1
    TIMEFRAME_M15 = 2

    def __init__(self, initialize_ok=True, symbol_known=True, rates=None):
        self._initialize_ok = initialize_ok
        self._symbol_known = symbol_known
        self._rates = rates
        self.shutdown_called = False
        self.copy_rates_calls = []

    def initialize(self):
        return self._initialize_ok

    def last_error(self):
        return (1, "mock error")

    def symbol_info(self, symbol):
        return object() if self._symbol_known else None

    def copy_rates_range(self, symbol, timeframe, start, end):
        self.copy_rates_calls.append((symbol, timeframe, start, end))
        return self._rates

    def shutdown(self):
        self.shutdown_called = True


@pytest.fixture
def mock_mt5(monkeypatch):
    def _install(**kwargs):
        fake = FakeMt5(**kwargs)
        monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
        return fake

    return _install


def test_unsupported_timeframe_raises_before_touching_mt5():
    # no mock installed at all — this must fail on input validation alone, without
    # ever trying to import/connect to MT5
    with pytest.raises(ValueError, match="unsupported timeframe"):
        load_ohlcv_from_mt5("EURUSD", "W1", datetime(2024, 1, 1), datetime(2024, 1, 2))


def test_missing_package_raises_runtime_error():
    # relies on MetaTrader5 genuinely not being installed in this test environment —
    # true by construction, since it's a Windows-only optional extra requiring a
    # locally running terminal
    assert "MetaTrader5" not in sys.modules
    with pytest.raises(RuntimeError, match="not installed"):
        load_ohlcv_from_mt5("EURUSD", "D1", datetime(2024, 1, 1), datetime(2024, 1, 2))


def test_successful_fetch_returns_sorted_bars(mock_mt5):
    rows = [
        (epoch(2024, 1, 2), 11, 11, 11, 11, 1000, 1, 0),
        (epoch(2024, 1, 1), 10, 10, 10, 10, 1000, 1, 0),  # out of order on purpose
    ]
    fake = mock_mt5(rates=make_rates(rows))

    bars = load_ohlcv_from_mt5("EURUSD", "D1", datetime(2024, 1, 1), datetime(2024, 1, 3))

    assert [b.timestamp for b in bars] == [datetime(2024, 1, 1), datetime(2024, 1, 2)]
    assert bars[0].symbol == "EURUSD"
    assert bars[0].open == 10.0
    assert bars[0].volume == 1000.0
    assert fake.shutdown_called is True
    assert fake.copy_rates_calls[0][1] == FakeMt5.TIMEFRAME_D1


def test_terminal_not_initialized_raises_runtime_error(mock_mt5):
    fake = mock_mt5(initialize_ok=False)
    with pytest.raises(RuntimeError, match="could not connect"):
        load_ohlcv_from_mt5("EURUSD", "D1", datetime(2024, 1, 1), datetime(2024, 1, 2))
    assert fake.shutdown_called is False  # nothing to shut down — initialize never succeeded


def test_unknown_symbol_raises_value_error(mock_mt5):
    fake = mock_mt5(symbol_known=False)
    with pytest.raises(ValueError, match="unknown to this MT5 terminal"):
        load_ohlcv_from_mt5("NOTASYMBOL", "D1", datetime(2024, 1, 1), datetime(2024, 1, 2))
    assert fake.shutdown_called is True


def test_empty_rates_raises_value_error(mock_mt5):
    fake = mock_mt5(rates=make_rates([]))
    with pytest.raises(ValueError, match="no bars returned"):
        load_ohlcv_from_mt5("EURUSD", "D1", datetime(2024, 1, 1), datetime(2024, 1, 2))
    assert fake.shutdown_called is True


def test_none_rates_raises_value_error(mock_mt5):
    fake = mock_mt5(rates=None)
    with pytest.raises(ValueError, match="no bars returned"):
        load_ohlcv_from_mt5("EURUSD", "D1", datetime(2024, 1, 1), datetime(2024, 1, 2))
    assert fake.shutdown_called is True


# --- mt5-fetch CLI --------------------------------------------------------------


def test_mt5_fetch_prints_summary(mock_mt5):
    rows = [
        (epoch(2024, 1, 1), 10, 12, 9, 11, 1000, 1, 0),
        (epoch(2024, 1, 2), 11, 13, 10, 12, 1000, 1, 0),
    ]
    mock_mt5(rates=make_rates(rows))

    runner = CliRunner()
    result = runner.invoke(
        mt5_fetch,
        ["--symbol", "EURUSD", "--timeframe", "D1", "--start", "2024-01-01", "--end", "2024-01-03"],
    )

    assert result.exit_code == 0, result.output
    assert "EURUSD (D1): 2 bars" in result.output
    assert "max=13.00000" in result.output  # highest high across both bars
    assert "min=9.00000" in result.output  # lowest low across both bars
