# Tests for engine/metrics.py — ticket 10
import math
import statistics
from datetime import datetime
from pathlib import Path

import pytest

from data.loader import load_ohlcv
from engine import metrics
from engine.engine import BacktestEngine, Trade
from engine.types import OrderAction
from strategies.ma_crossover import MaCrossover

FIXTURE = Path(__file__).parent / "fixtures" / "sample_20bars.csv"


def make_trade(action, price, quantity=1, timestamp=datetime(2024, 1, 1)):
    return Trade(timestamp=timestamp, symbol="EURUSD", action=action, quantity=quantity, price=price, tag=None)


# --- total_return -----------------------------------------------------------------


def test_total_return_positive():
    assert metrics.total_return(10000.0, 10004.0) == pytest.approx(0.0004)


def test_total_return_negative():
    assert metrics.total_return(10000.0, 9000.0) == pytest.approx(-0.10)


# --- sharpe_ratio -------------------------------------------------------------------


def test_sharpe_ratio_matches_manual_formula():
    equity_curve = [100.0, 110.0, 105.0, 115.0]
    returns = [equity_curve[i] / equity_curve[i - 1] - 1 for i in range(1, len(equity_curve))]
    expected = statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(252)
    assert metrics.sharpe_ratio(equity_curve, annualization_factor=252) == pytest.approx(expected)


def test_sharpe_ratio_uses_the_given_annualization_factor():
    equity_curve = [100.0, 110.0, 105.0, 115.0]
    daily = metrics.sharpe_ratio(equity_curve, annualization_factor=252)
    hourly = metrics.sharpe_ratio(equity_curve, annualization_factor=252 * 24)
    assert hourly == pytest.approx(daily * math.sqrt(24))


def test_sharpe_ratio_zero_variance_returns_zero():
    # constant 10% return every period -> zero stdev -> undefined ratio, not division by zero
    assert metrics.sharpe_ratio([100.0, 110.0, 121.0], annualization_factor=252) == 0.0


def test_sharpe_ratio_insufficient_data_returns_zero():
    assert metrics.sharpe_ratio([100.0], annualization_factor=252) == 0.0
    assert metrics.sharpe_ratio([100.0, 110.0], annualization_factor=252) == 0.0


# --- max_drawdown ---------------------------------------------------------------


def test_max_drawdown_hand_calculated():
    # peak 120 after bar 2, trough 90 at bar 3 -> (120-90)/120 = 0.25
    assert metrics.max_drawdown([100.0, 120.0, 90.0, 110.0]) == pytest.approx(0.25)


def test_max_drawdown_no_decline_is_zero():
    assert metrics.max_drawdown([100.0, 105.0, 110.0]) == 0.0


def test_max_drawdown_on_known_answer_equity_curve():
    bars = load_ohlcv(str(FIXTURE), symbol="EURUSD")
    result = BacktestEngine(MaCrossover(), initial_cash=10000.0, fill_timing="immediate").run(bars)
    curve = [point.equity for point in result.equity_curve]
    # peak 10004 at bar 9, trough 10002 at bars 11-18 -> (10004-10002)/10004
    assert metrics.max_drawdown(curve) == pytest.approx(2 / 10004)


# --- win_rate ---------------------------------------------------------------------


def test_win_rate_hand_calculated():
    assert metrics.win_rate([2.0, -1.0, 3.0, -1.0]) == pytest.approx(0.5)


def test_win_rate_no_trades_is_none():
    assert metrics.win_rate([]) is None


# --- profit_factor ------------------------------------------------------------------


def test_profit_factor_hand_calculated():
    assert metrics.profit_factor([2.0, -1.0, 3.0, -1.0]) == pytest.approx(5.0 / 2.0)


def test_profit_factor_no_losses_is_none():
    assert metrics.profit_factor([2.0, 3.0]) is None


def test_profit_factor_no_profit_is_zero():
    assert metrics.profit_factor([-1.0, -2.0]) == 0.0


# --- realized_pnls ------------------------------------------------------------------


def test_realized_pnls_pairs_buy_and_close():
    trades = [
        make_trade(OrderAction.BUY, 11.0),
        make_trade(OrderAction.CLOSE, 13.0),
    ]
    assert metrics.realized_pnls(trades) == pytest.approx([2.0])


def test_realized_pnls_ignores_a_trailing_unmatched_open():
    trades = [
        make_trade(OrderAction.BUY, 11.0),
        make_trade(OrderAction.CLOSE, 13.0),
        make_trade(OrderAction.BUY, 11.0),  # still open — no matching CLOSE
    ]
    assert metrics.realized_pnls(trades) == pytest.approx([2.0])


def test_realized_pnls_on_known_answer_dataset():
    bars = load_ohlcv(str(FIXTURE), symbol="EURUSD")
    result = BacktestEngine(MaCrossover(), initial_cash=10000.0, fill_timing="immediate").run(bars)
    pnls = metrics.realized_pnls(result.trades)
    assert pnls == pytest.approx([2.0])
    assert metrics.win_rate(pnls) == pytest.approx(1.0)
    assert metrics.profit_factor(pnls) is None
