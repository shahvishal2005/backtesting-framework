# Known-answer test: MA crossover, both fill-timing rules — tickets 6 and 7
from datetime import datetime
from pathlib import Path

import pytest

from data.loader import load_ohlcv
from engine.costs import CostModel, fixed_commission, fixed_slippage
from engine.engine import BacktestEngine, Trade
from engine.types import OrderAction
from strategies.ma_crossover import MaCrossover

FIXTURE = Path(__file__).parent / "fixtures" / "sample_20bars.csv"


def load_bars():
    return load_ohlcv(str(FIXTURE), symbol="EURUSD")


def test_known_answer_immediate_fill_v0():
    """Section 6's known-answer test, immediate-fill-at-signal-close rule (ticket 6)."""
    bars = load_bars()
    result = BacktestEngine(
        MaCrossover(), initial_cash=10000.0, fill_timing="immediate"
    ).run(bars)

    expected_trades = [
        Trade(datetime(2024, 1, 5), "EURUSD", OrderAction.BUY, 1, 11.0, None),
        Trade(datetime(2024, 1, 11), "EURUSD", OrderAction.CLOSE, 1, 13.0, None),
        Trade(datetime(2024, 1, 18), "EURUSD", OrderAction.BUY, 1, 11.0, None),
    ]
    assert result.trades == expected_trades
    assert result.final_equity == pytest.approx(10004.00)


def test_known_answer_next_bar_open_fill():
    """Section 6's known-answer test, next-bar-open fill rule (ticket 7, now the
    engine's default)."""
    bars = load_bars()
    result = BacktestEngine(
        MaCrossover(), initial_cash=10000.0, fill_timing="next_bar_open"
    ).run(bars)

    expected_trades = [
        Trade(datetime(2024, 1, 6), "EURUSD", OrderAction.BUY, 1, 12.0, None),
        Trade(datetime(2024, 1, 12), "EURUSD", OrderAction.CLOSE, 1, 12.0, None),
        Trade(datetime(2024, 1, 19), "EURUSD", OrderAction.BUY, 1, 12.0, None),
    ]
    assert result.trades == expected_trades
    assert result.final_equity == pytest.approx(10001.00)


def test_known_answer_with_nonzero_cost_model():
    """ticket 8: same fixture/strategy, immediate fill, $1 fixed commission + $0.05
    fixed slippage per fill (both applied against the trader — BUY pays more, CLOSE
    receives less), hand-computed cash flow:
      BUY  @ 11.00 + 0.05 slippage = 11.05, cash -= 11.05, -1.00 commission
      CLOSE@ 13.00 - 0.05 slippage = 12.95, cash += 12.95, -1.00 commission
      BUY  @ 11.00 + 0.05 slippage = 11.05, cash -= 11.05, -1.00 commission
      mark-to-market at bar 20 close = 13.00 (no slippage on marks)
      final equity = 10000 - 11.05 - 1 + 12.95 - 1 - 11.05 - 1 + 13.00 = 10000.85
    """
    bars = load_bars()
    cost_model = CostModel(commission=fixed_commission(1.0), slippage=fixed_slippage(0.05))
    result = BacktestEngine(
        MaCrossover(), initial_cash=10000.0, fill_timing="immediate", cost_model=cost_model
    ).run(bars)

    expected_trades = [
        Trade(datetime(2024, 1, 5), "EURUSD", OrderAction.BUY, 1, 11.05, None),
        Trade(datetime(2024, 1, 11), "EURUSD", OrderAction.CLOSE, 1, 12.95, None),
        Trade(datetime(2024, 1, 18), "EURUSD", OrderAction.BUY, 1, 11.05, None),
    ]
    assert result.trades == expected_trades
    assert result.final_equity == pytest.approx(10000.85)
