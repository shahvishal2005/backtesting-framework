# Tests for engine.run_smoke_test — ticket 12
import time
from pathlib import Path

from data.loader import load_ohlcv
from engine.engine import BacktestEngine, run_smoke_test
from engine.types import Bar, Order, State
from strategies.base import Strategy
from strategies.buy_and_hold import BuyAndHold

FIXTURE = Path(__file__).parent / "fixtures" / "sample_20bars.csv"


class _CrashingStrategy(Strategy):
    def on_bar(self, bar: Bar, state: State) -> list[Order]:
        raise ZeroDivisionError("boom")


class _SlowStrategy(Strategy):
    def on_bar(self, bar: Bar, state: State) -> list[Order]:
        time.sleep(0.2)
        return []


def load_bars():
    return load_ohlcv(str(FIXTURE), symbol="EURUSD")


def test_smoke_test_passes_for_a_working_strategy():
    bars = load_bars()
    engine = BacktestEngine(BuyAndHold())
    result = run_smoke_test(engine, bars, n_bars=5, timeout_seconds=5.0)
    assert result.ok is True
    assert result.error is None
    assert result.bars_run == 5


def test_smoke_test_catches_exceptions_without_propagating():
    bars = load_bars()
    engine = BacktestEngine(_CrashingStrategy())
    result = run_smoke_test(engine, bars, n_bars=5, timeout_seconds=5.0)
    assert result.ok is False
    assert "ZeroDivisionError" in result.error
    assert "boom" in result.error


def test_smoke_test_times_out_on_a_hanging_strategy():
    bars = load_bars()
    engine = BacktestEngine(_SlowStrategy())
    result = run_smoke_test(engine, bars, n_bars=5, timeout_seconds=0.05)
    assert result.ok is False
    assert "timeout" in result.error


def test_smoke_test_uses_only_the_last_n_bars():
    bars = load_bars()
    engine = BacktestEngine(BuyAndHold())
    result = run_smoke_test(engine, bars, n_bars=3, timeout_seconds=5.0)
    assert result.bars_run == 3


def test_smoke_test_clamps_to_full_bars_when_n_bars_exceeds_length():
    bars = load_bars()
    engine = BacktestEngine(BuyAndHold())
    result = run_smoke_test(engine, bars, n_bars=1000, timeout_seconds=5.0)
    assert result.bars_run == len(bars)


def test_smoke_test_zero_n_bars_runs_nothing():
    bars = load_bars()
    engine = BacktestEngine(BuyAndHold())
    result = run_smoke_test(engine, bars, n_bars=0, timeout_seconds=5.0)
    assert result.ok is True
    assert result.bars_run == 0
