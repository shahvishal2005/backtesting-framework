# Tests for cli.py — ticket 11
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli import run_backtest
from data.loader import load_ohlcv
from engine.engine import BacktestEngine
from engine.metrics import (
    max_drawdown,
    profit_factor,
    realized_pnls,
    sharpe_ratio,
    total_return,
    win_rate,
)
from strategies.ma_crossover import MaCrossover

FIXTURE = Path(__file__).parent / "fixtures" / "sample_20bars.csv"


def invoke(tmp_path, extra_args=(), output_name="results.json"):
    output_path = tmp_path / output_name
    runner = CliRunner()
    result = runner.invoke(
        run_backtest,
        [
            "--data", str(FIXTURE),
            "--symbol", "EURUSD",
            "--strategy", "strategies.ma_crossover:MaCrossover",
            "--output", str(output_path),
            *extra_args,
        ],
    )
    return result, output_path


def test_run_backtest_writes_expected_json_schema(tmp_path):
    result, output_path = invoke(tmp_path)
    assert result.exit_code == 0, result.output

    with open(output_path) as f:
        payload = json.load(f)

    # cross-check against calling the library directly with the same (default) settings
    bars = load_ohlcv(str(FIXTURE), symbol="EURUSD")
    expected = BacktestEngine(MaCrossover(), initial_cash=10000.0).run(bars)
    pnls = realized_pnls(expected.trades)
    equity_values = [p.equity for p in expected.equity_curve]

    assert payload["symbol"] == "EURUSD"
    assert payload["final_equity"] == pytest.approx(expected.final_equity)
    assert payload["metrics"]["total_return"] == pytest.approx(
        total_return(10000.0, expected.final_equity)
    )
    assert payload["metrics"]["sharpe"] == pytest.approx(sharpe_ratio(equity_values, 252))
    assert payload["metrics"]["max_drawdown"] == pytest.approx(max_drawdown(equity_values))
    assert payload["metrics"]["win_rate"] == pytest.approx(win_rate(pnls))
    assert payload["metrics"]["profit_factor"] == profit_factor(pnls)

    assert len(payload["trades"]) == len(expected.trades)
    assert payload["trades"][0]["action"] == "BUY"
    assert payload["trades"][0]["price"] == pytest.approx(expected.trades[0].price)
    assert payload["trades"][0]["timestamp"] == expected.trades[0].timestamp.isoformat()
    assert len(payload["equity_curve"]) == len(expected.equity_curve)


def test_run_backtest_default_engine_settings_known_answer(tmp_path):
    # default fill_timing is next_bar_open (ticket 7): BUY@12 -> CLOSE@12 -> BUY@12,
    # realized pnl = 0.0, so win_rate=0.0 (not a winning trade) and profit_factor=None
    # (no losing trade either)
    result, output_path = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    with open(output_path) as f:
        payload = json.load(f)

    assert payload["final_equity"] == pytest.approx(10001.00)
    assert payload["metrics"]["total_return"] == pytest.approx(0.0001)
    assert payload["metrics"]["win_rate"] == pytest.approx(0.0)
    assert payload["metrics"]["profit_factor"] is None
    assert payload["trades"][0]["timestamp"] == "2024-01-06T00:00:00"
    assert payload["trades"][0]["price"] == pytest.approx(12.0)


def test_run_backtest_respects_timeframe_flag(tmp_path):
    daily_result, daily_path = invoke(
        tmp_path, extra_args=["--timeframe", "daily"], output_name="daily.json"
    )
    hourly_result, hourly_path = invoke(
        tmp_path, extra_args=["--timeframe", "hourly"], output_name="hourly.json"
    )
    assert daily_result.exit_code == 0 and hourly_result.exit_code == 0

    daily_sharpe = json.load(open(daily_path))["metrics"]["sharpe"]
    hourly_sharpe = json.load(open(hourly_path))["metrics"]["sharpe"]
    assert hourly_sharpe == pytest.approx(daily_sharpe * (24**0.5))


def test_smoke_test_flag_passes_and_skips_output(tmp_path):
    # the underlying crash/timeout-catching behavior is exercised directly and
    # thoroughly in test_smoke_test.py; this only needs to confirm the CLI wiring —
    # that --smoke-test actually calls run_smoke_test and reports success, skipping
    # the full backtest's --output write
    result, output_path = invoke(tmp_path, extra_args=["--smoke-test", "--smoke-test-bars", "5"])
    assert result.exit_code == 0, result.output
    assert "Smoke test passed" in result.output
    assert not output_path.exists()


def test_invalid_strategy_spec_fails(tmp_path):
    result, _ = invoke(tmp_path, extra_args=["--strategy", "strategies.ma_crossover"])  # missing ":Class"
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
