"""run-backtest CLI entry point: loader -> engine -> metrics -> JSON output."""

import importlib
import json

import click

from data.loader import load_ohlcv
from data.mt5_loader import TIMEFRAME_ATTRS, load_ohlcv_from_mt5
from engine.engine import BacktestEngine, run_smoke_test
from engine.metrics import (
    ANNUALIZATION_FACTORS,
    max_drawdown,
    profit_factor,
    realized_pnls,
    sharpe_ratio,
    total_return,
    win_rate,
)
from strategies.base import Strategy


def _load_strategy_class(spec: str) -> type[Strategy]:
    """Resolves 'module.path:ClassName' (e.g. 'strategies.ma_crossover:MaCrossover')
    to the class object."""
    module_name, sep, class_name = spec.partition(":")
    if not sep:
        raise ValueError(f"--strategy must be in 'module:ClassName' form, got {spec!r}")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


@click.command(name="run-backtest")
@click.option("--data", "data_path", required=True, type=click.Path(exists=True), help="Path to a CSV/Parquet OHLCV file.")
@click.option("--symbol", required=True, help="Symbol to assign the loaded bars.")
@click.option("--strategy", "strategy_spec", required=True, help="Strategy class as 'module.path:ClassName'.")
@click.option("--output", "output_path", required=True, type=click.Path(), help="Path to write the results JSON to.")
@click.option("--initial-cash", default=10000.0, show_default=True, type=float)
@click.option(
    "--timeframe",
    default="daily",
    show_default=True,
    type=click.Choice(sorted(ANNUALIZATION_FACTORS)),
    help="Bar timeframe — used only to annualize the Sharpe ratio (Section 7).",
)
@click.option(
    "--smoke-test",
    is_flag=True,
    default=False,
    help="Run only a quick sanity check (last N bars, under a timeout) instead of the full backtest.",
)
@click.option("--smoke-test-bars", default=20, show_default=True, type=int, help="Trailing bars used by --smoke-test.")
@click.option("--smoke-test-timeout", default=5.0, show_default=True, type=float, help="Timeout in seconds for --smoke-test.")
def run_backtest(
    data_path,
    symbol,
    strategy_spec,
    output_path,
    initial_cash,
    timeframe,
    smoke_test,
    smoke_test_bars,
    smoke_test_timeout,
):
    """Loads OHLCV data, runs a strategy through the backtest engine, and writes a
    results JSON with trades, equity curve, and metrics. With --smoke-test, runs only
    a quick sanity check instead and skips writing --output."""
    bars = load_ohlcv(data_path, symbol=symbol)
    strategy_cls = _load_strategy_class(strategy_spec)
    engine = BacktestEngine(strategy_cls(), initial_cash=initial_cash)

    if smoke_test:
        smoke_result = run_smoke_test(
            engine, bars, n_bars=smoke_test_bars, timeout_seconds=smoke_test_timeout
        )
        if smoke_result.ok:
            click.echo(
                f"Smoke test passed: {smoke_result.bars_run} bars in "
                f"{smoke_result.elapsed_seconds:.3f}s"
            )
            return
        click.echo(
            f"Smoke test FAILED after {smoke_result.elapsed_seconds:.3f}s on "
            f"{smoke_result.bars_run} bars: {smoke_result.error}",
            err=True,
        )
        raise SystemExit(1)

    result = engine.run(bars)

    pnls = realized_pnls(result.trades)
    equity_values = [point.equity for point in result.equity_curve]
    annualization_factor = ANNUALIZATION_FACTORS[timeframe]

    output = {
        "symbol": symbol,
        "final_equity": result.final_equity,
        "metrics": {
            "total_return": total_return(initial_cash, result.final_equity),
            "sharpe": sharpe_ratio(equity_values, annualization_factor),
            "max_drawdown": max_drawdown(equity_values),
            "win_rate": win_rate(pnls),
            "profit_factor": profit_factor(pnls),
        },
        "trades": [
            {
                "timestamp": trade.timestamp.isoformat(),
                "action": trade.action.value,
                "quantity": trade.quantity,
                "price": trade.price,
                "tag": trade.tag,
            }
            for trade in result.trades
        ],
        "equity_curve": [
            {"timestamp": point.timestamp.isoformat(), "equity": point.equity}
            for point in result.equity_curve
        ],
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    click.echo(f"Wrote results to {output_path}")


@click.command(name="mt5-fetch")
@click.option("--symbol", required=True, help="Symbol as known to the MT5 terminal, e.g. EURUSD.")
@click.option("--timeframe", required=True, type=click.Choice(sorted(TIMEFRAME_ATTRS)))
@click.option("--start", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--end", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
def mt5_fetch(symbol, timeframe, start, end):
    """Fetches a range of historical bars from a running MT5 terminal and prints a
    summary table — a sanity-check step (Section 4a), not part of run-backtest's
    output pipeline."""
    bars = load_ohlcv_from_mt5(symbol, timeframe, start, end)

    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]

    click.echo(f"{symbol} ({timeframe}): {len(bars)} bars")
    click.echo(f"  range: {bars[0].timestamp} -> {bars[-1].timestamp}")
    click.echo(f"  close: min={min(closes):.5f}  max={max(closes):.5f}")
    click.echo(f"  high:  max={max(highs):.5f}")
    click.echo(f"  low:   min={min(lows):.5f}")


if __name__ == "__main__":
    run_backtest()
