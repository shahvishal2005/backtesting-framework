"""Runs BacktestEngine.run() for one strategy, in isolation, as its own process.

Invoked by sandbox.py via subprocess — never imported directly by the web server.
Reads a job spec as JSON from stdin: {strategy_id, initial_cash, bars: [...]}. Writes
the result (or an error) as JSON to stdout, exit code 0 on success, 1 on failure.

This is the actual sandboxing boundary: the only place a strategy's on_bar() ever
executes is inside this subprocess, never inside the FastAPI worker — matching the
Phase 1 architecture doc's handoff note that "sandboxing wraps the strategy execution
step," not the whole request.
"""

import json
import sys
from datetime import datetime

from engine.engine import BacktestEngine
from engine.types import Bar
from strategy_registry import AVAILABLE_STRATEGIES


def main() -> None:
    job = json.loads(sys.stdin.read())
    strategy_id = job["strategy_id"]
    if strategy_id not in AVAILABLE_STRATEGIES:
        raise ValueError(f"unknown strategy {strategy_id!r}")

    bars = [
        Bar(
            timestamp=datetime.fromisoformat(b["timestamp"]),
            symbol=b["symbol"],
            open=b["open"],
            high=b["high"],
            low=b["low"],
            close=b["close"],
            volume=b["volume"],
        )
        for b in job["bars"]
    ]

    _name, strategy_cls = AVAILABLE_STRATEGIES[strategy_id]
    result = BacktestEngine(strategy_cls(), initial_cash=job["initial_cash"]).run(bars)

    output = {
        "final_equity": result.final_equity,
        "trades": [
            {
                "timestamp": trade.timestamp.isoformat(),
                "symbol": trade.symbol,
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
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: broad on purpose — report any failure as JSON
        # for the parent process to parse cleanly, not a raw traceback on stderr
        sys.stdout.write(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)
