# Tests for engine v0 against the buy-and-hold strategy — ticket 5
from pathlib import Path

import pytest

from data.loader import load_ohlcv
from engine.engine import BacktestEngine
from engine.types import OrderAction
from strategies.buy_and_hold import BuyAndHold

FIXTURE = Path(__file__).parent / "fixtures" / "sample_20bars.csv"


def load_bars():
    return load_ohlcv(str(FIXTURE), symbol="EURUSD")


def test_only_one_trade_is_ever_recorded():
    bars = load_bars()
    result = BacktestEngine(BuyAndHold(), initial_cash=10000.0, fill_timing="immediate").run(bars)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.symbol == "EURUSD"
    assert trade.action == OrderAction.BUY
    assert trade.quantity == 1
    assert trade.price == bars[0].close  # immediate fill, at the signal bar's own close


def test_equity_tracks_price_after_initial_buy():
    bars = load_bars()
    result = BacktestEngine(BuyAndHold(), initial_cash=10000.0, fill_timing="immediate").run(bars)
    entry_price = bars[0].close
    cash_after_buy = 10000.0 - entry_price

    assert len(result.equity_curve) == len(bars)
    for bar, point in zip(bars, result.equity_curve):
        assert point.timestamp == bar.timestamp
        assert point.equity == pytest.approx(cash_after_buy + bar.close)


def test_final_equity_matches_last_bar_close():
    bars = load_bars()
    result = BacktestEngine(BuyAndHold(), initial_cash=10000.0, fill_timing="immediate").run(bars)
    entry_price = bars[0].close
    expected = 10000.0 - entry_price + bars[-1].close
    assert result.final_equity == pytest.approx(expected)


def test_default_fill_timing_is_next_bar_open():
    # ticket 7: next_bar_open is now the engine's default, per Section 5 point 4
    bars = load_bars()
    result = BacktestEngine(BuyAndHold(), initial_cash=10000.0).run(bars)  # no override
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.timestamp == bars[1].timestamp  # fills on the bar after the signal
    assert trade.price == bars[1].open


def test_unsupported_fill_timing_rejected():
    with pytest.raises(ValueError, match="fill_timing"):
        BacktestEngine(BuyAndHold(), fill_timing="end_of_week")


def test_empty_bars_returns_initial_cash_as_final_equity():
    result = BacktestEngine(BuyAndHold(), initial_cash=10000.0).run([])
    assert result.trades == []
    assert result.equity_curve == []
    assert result.final_equity == 10000.0
