# Backtest Core — Phase 1 Build Spec

**Scope**: a plain Python library + CLI that loads offline candle data, runs a strategy
against a fixed interface, and produces an accurate trade log, equity curve, and metrics.

**Explicitly out of scope for Phase 1**: web UI, sandboxing/multi-tenancy, MQL/Pine
adapters, online data fetching (general broker/exchange APIs), database storage. Those
come in later phases — see the main architecture document.

**Narrow exception**: a read-only MT5 historical-data connector (Section 4a below) is
pulled into Phase 1, since forex/MQL5 testing depends on validating against the same
candles MT5 itself would serve. This is data fetch only — running an EA inside MT5
stays a later, separate piece of work (architecture doc, Section 5.3).

**Definition of done for Phase 1**: a known-answer test (Section 6) passes exactly,
proving the engine's trade and equity output matches a hand-calculated result on a
reference strategy.

---

## 1. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | matches the rest of the ecosystem (pandas, existing strategy code) |
| Data handling | pandas | standard, matches offline CSV/Parquet inputs |
| Validation | `dataclasses` (stdlib) | zero dependency; upgrade to `pydantic` later if runtime validation of untrusted input is needed |
| Testing | `pytest` | standard, good fixture support for known-answer tests |
| CLI | `argparse` (stdlib) or `click` | either is fine; `click` if the CLI grows many options |
| Storage | flat files only (CSV/Parquet) | no DB in Phase 1 — defer until the web layer needs one |

No web framework, no job queue, no container tooling in this phase. Those are Phase 2
concerns (see the architecture document, Section 11.2).

**Pinned dependencies** (`pyproject.toml`):

```toml
[project]
name = "backtest-core"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.2,<3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "click>=8.1",
]
mt5 = [
    "MetaTrader5>=5.0.45",
]
```

The `mt5` extra is Windows-only (the `MetaTrader5` package wraps a locally installed MT5
terminal via IPC — there is no Linux/Mac build) and is only needed for ticket 13. The
core engine, loader, and CLI have no dependency on it.

**Environment setup** (ticket 1 should produce a repo where this works):

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

**Error-handling convention**: raise standard exceptions (`ValueError` for bad input
data/config, `RuntimeError` for engine-internal invariant violations) with a clear
message — never silently skip bad data or swallow exceptions. This matters more than
usual here because a swallowed error in a backtest produces a wrong-but-plausible
result, not a visible crash.

---

## 2. Repository structure

```
backtest-core/
  engine/
    __init__.py
    types.py          # Bar, Order, Position, State
    engine.py          # BacktestEngine — the bar-by-bar loop
    costs.py           # commission/slippage models (pluggable functions)
    metrics.py          # Sharpe, drawdown, win rate, profit factor
  data/
    schema.py            # expected column names/dtypes
    loader.py             # CSV/Parquet -> list[Bar]
    mt5_loader.py          # MT5 terminal -> list[Bar] (ticket 13, optional mt5 extra)
  strategies/
    base.py                # Strategy interface (abstract base class)
    buy_and_hold.py        # trivial reference strategy (ticket 4)
    ma_crossover.py        # reference strategy for the known-answer test (ticket 6)
  tests/
    fixtures/
      sample_20bars.csv    # small synthetic dataset used by known-answer tests
    test_types.py
    test_loader.py
    test_mt5_loader.py     # mocked MT5 terminal calls (ticket 13)
    test_engine_buy_and_hold.py
    test_engine_ma_crossover.py
    test_engine_intrabar_path.py
    test_costs.py
    test_metrics.py
  cli.py                    # run-backtest entry point
  pyproject.toml
  README.md
```

---

## 3. Core interface (concrete, not prose)

This is the contract every later adapter (MQL, Pine) must eventually produce. Define it
exactly like this — later modules should conform to it, not redefine it.

```python
# engine/types.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


@dataclass(frozen=True)
class Order:
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
    symbol: str
    quantity: float
    avg_price: float
    stop_loss: float | None = None     # carried from the Order that opened the position,
    take_profit: float | None = None   # so the engine can evaluate Section 5.1 each bar


@dataclass
class State:
    current_bar: Bar
    lookback: list[Bar]                 # prior bars, most recent last
    positions: dict[str, Position]
    cash: float
    equity: float
```

```python
# strategies/base.py
from abc import ABC, abstractmethod
from engine.types import Bar, Order, State


class Strategy(ABC):
    @abstractmethod
    def on_bar(self, bar: Bar, state: State) -> list[Order]:
        """Given the current bar and account state, return zero or more orders."""
        ...
```

---

## 4. Data schema and loader

**Expected input CSV columns** (case-insensitive, reorderable): `timestamp, open, high,
low, close, volume`. One file per symbol; the symbol itself comes from a `--symbol`
CLI argument or the filename, not a column.

**Loader signature**:

```python
# data/loader.py
def load_ohlcv(path: str, symbol: str) -> list[Bar]:
    """Reads a CSV/Parquet file, validates columns/dtypes, sorts by timestamp,
    and returns a list of Bar objects. Raises ValueError on missing columns,
    non-monotonic timestamps, or NaN values in required fields."""
```

---

## 4a. MT5 data connector (ticket 13)

Read-only historical-data fetch from a locally running MT5 terminal, so forex/MQL5
strategies get backtested against the same candles MT5 itself would serve. This does
**not** execute EAs or place trades — it only pulls bars, converting them into the same
`Bar` objects the CSV loader produces, so the engine's input path never branches on
data source.

**Loader signature**:

```python
# data/mt5_loader.py
def load_ohlcv_from_mt5(
    symbol: str,
    timeframe: str,       # e.g. "M1", "M15", "H1", "D1" — mapped to MetaTrader5's TIMEFRAME_* constants
    start: datetime,
    end: datetime,
) -> list[Bar]:
    """Connects to a running, logged-in MT5 terminal, fetches historical rates via
    MetaTrader5.copy_rates_range(), and returns Bar objects sorted by timestamp.
    Raises RuntimeError if the terminal isn't running/logged in, ValueError if the
    symbol is unknown to the terminal or the range returns no bars."""
```

**Requirements/constraints**:
- Requires an MT5 terminal installed and logged into a broker account on the same
  Windows machine — the `MetaTrader5` package talks to it over local IPC, not the
  network directly.
- `mt5.initialize()` / `mt5.shutdown()` bracket every call; don't leave a dangling
  connection across test runs.
- Output must satisfy the exact same `Bar` contract as `load_ohlcv()` (Section 3) —
  no MT5-specific fields leak into the engine.

**Display**: a small `mt5-fetch` CLI command (or a `--plot` flag using `matplotlib`,
dev-only dependency) that fetches a range and prints a summary table (bar count,
date range, OHLC min/max) or renders a candle chart — a sanity-check step, not part
of the `run-backtest` output pipeline in Section 8.

**Testing approach**: `test_mt5_loader.py` mocks `MetaTrader5.copy_rates_range` (no
real terminal needed in CI) and asserts the schema conversion, timestamp sorting, and
error paths. This keeps the known-answer tests in Section 6 — which must stay
deterministic and CI-runnable without a Windows terminal — completely independent of
this connector.

---

## 5. Engine behavior spec

Implement as a straightforward bar-by-bar loop — **not vectorized** — since the engine
must support state carried between bars (open positions, indicator lookbacks) exactly
as a real EA or Pine strategy would.

1. Iterate bars in timestamp order.
2. Maintain a rolling `lookback` window and current `positions`/`cash`/`equity` in `State`.
3. Call `strategy.on_bar(bar, state)`; collect returned orders.
4. **Fill-timing rule (default)**: market orders fill at the **next bar's open**, not
   the signal bar's close. This must be a named, overridable parameter — don't hardcode
   it, since it directly affects backtest realism (see architecture doc, Section 7.2).
5. Apply the cost model (Section 6 below) to each fill.
6. Update `positions`, `cash`, and `equity` after every bar (not just on trade close) so
   intraday drawdown can be computed correctly later.
7. Record every fill to a trade log (timestamp, symbol, action, quantity, price, tag).
8. Determinism requirement: identical input data + identical strategy + identical
   parameters must always produce byte-identical output. No wall-clock time, randomness,
   or unseeded state anywhere in the engine.
9. **Order quantity is fixed at 1 unit for all of Phase 1** — every reference/test
   strategy always trades quantity=1. `Order.quantity` stays a real field (don't remove
   it), but no strategy in this phase computes it dynamically. Dynamic position sizing
   (risk %, account-based sizing) is a later, separate ticket once the core loop is
   trusted — this keeps quantity out of the known-answer test's math entirely for now.

### 5.1 Intrabar path resolution (SL/TP ordering ambiguity)

A single OHLC bar doesn't tell you the *order* prices occurred in — if a bar's range
touches both an open position's stop-loss and its take-profit, an OHLC-only engine
cannot know which was hit first without an explicit assumption. This is a real,
well-known limitation (it's why MetaTrader's own tester has an "every tick" mode as its
most trusted setting), and it needs a named, testable rule rather than silent behavior.

**Engine parameter**: `intrabar_path`, one of:

- `"open_high_low_close"` — assumes price moves open → high → low → close within the bar
- `"open_low_high_close"` — assumes price moves open → low → high → close within the bar
- `"pessimistic"` (**default**) — for a long position, behaves like `open_low_high_close`
  (stop-loss side reached first); for a short position, behaves like
  `open_high_low_close`. This is the conservative choice — it never overstates a
  strategy's performance — and is the right default for a tool whose job is evaluating
  strategies honestly.
- `"optimistic"` — the opposite of `pessimistic`, useful for sanity-checking a
  best-case/worst-case performance range on the same strategy.

Whichever path is selected, the engine walks it in order and closes the position at the
first level (stop-loss or take-profit) it reaches; if neither is reached, the position
stays open at the bar's close. This rule only matters when a position has both an SL and
a TP set and the bar's range reaches both — most bars won't trigger it at all.

**True tick-data replay** (a data source with every actual price change, not just
OHLC) removes this ambiguity entirely instead of assuming it away, and is worth adding
later — but only for the MQL/generic-code path. Pine Script strategies execute on bar
close only and have no concept of ticks, so tick replay can never apply to them; adding
it earlier than the MQL adapter (Phase 2) would be wasted effort. Treat it as a Phase 3
enhancement, scoped specifically to MQL, once the OHLC-based engine and its adapters are
already trusted.

---

## 6. Known-answer test (the Phase 1 acceptance gate)

Before trusting the engine on any real strategy, it must reproduce a hand-verified
result exactly — not an approximately-right one. Below is the actual fixture and the
actual expected numbers, computed and checked (not left as an exercise).

**Fixture** — `tests/fixtures/sample_20bars.csv` (flat OHLC for a clean test; use this
exact data):

```csv
timestamp,open,high,low,close,volume
2024-01-01,10,10,10,10,1000
2024-01-02,10,10,10,10,1000
2024-01-03,10,10,10,10,1000
2024-01-04,10,10,10,10,1000
2024-01-05,11,11,11,11,1000
2024-01-06,12,12,12,12,1000
2024-01-07,13,13,13,13,1000
2024-01-08,14,14,14,14,1000
2024-01-09,15,15,15,15,1000
2024-01-10,14,14,14,14,1000
2024-01-11,13,13,13,13,1000
2024-01-12,12,12,12,12,1000
2024-01-13,11,11,11,11,1000
2024-01-14,10,10,10,10,1000
2024-01-15,9,9,9,9,1000
2024-01-16,9,9,9,9,1000
2024-01-17,10,10,10,10,1000
2024-01-18,11,11,11,11,1000
2024-01-19,12,12,12,12,1000
2024-01-20,13,13,13,13,1000
```

**Reference strategy**: `strategies/ma_crossover.py` — MA(2) vs. MA(4) of close price.
Buy 1 unit when MA(2) crosses above MA(4); close the position when it crosses back
below. On this fixture, MA(2)/MA(4) cross exactly three times:

| Bar (date) | MA(2) | MA(4) | Crossover | Signal |
|---|---|---|---|---|
| 2024-01-05 | 10.5 | 10.25 | up | BUY |
| 2024-01-11 | 13.5 | 14.00 | down | CLOSE |
| 2024-01-18 | 11.5 | 10.50 | up | BUY (still open at bar 20) |

**Expected result, immediate-fill-at-signal-close rule (v0 engine, ticket 5–6)**,
starting cash = 10000, quantity = 1, zero cost model:

- Trade 1: BUY @ 11.00 (2024-01-05) → CLOSE @ 13.00 (2024-01-11) → realized P/L = **+2.00**
- Trade 2: BUY @ 11.00 (2024-01-18) → still open at bar 20; mark-to-market at close
  13.00 on 2024-01-20 → unrealized P/L = **+2.00**
- **Expected final equity: 10004.00**

**Expected result, next-bar-open fill rule (ticket 7)**, same starting conditions:

- Trade 1: BUY @ 12.00 (fills 2024-01-06, the bar after the 01-05 signal) → CLOSE @
  12.00 (fills 2024-01-12, the bar after the 01-11 signal) → realized P/L = **0.00**
- Trade 2: BUY @ 12.00 (fills 2024-01-19) → still open at bar 20; mark-to-market at
  close 13.00 on 2024-01-20 → unrealized P/L = **+1.00**
- **Expected final equity: 10001.00**

`tests/test_engine_ma_crossover.py` must assert both trade lists and both final-equity
values exactly (run the same fixture twice — once per fill rule — rather than only
testing whichever rule is currently implemented). This test is the single most
important artifact in Phase 1 — every later change to the engine must keep it passing.

### 6.1 Known-answer test — intrabar path resolution

A separate, minimal test proves the `intrabar_path` rule (Section 5.1) actually
resolves SL/TP ambiguity as specified.

**Setup**: a long position already open at entry price 100.0, with stop-loss = 95.0 and
take-profit = 108.0. The next bar has `open=100, high=110, low=90, close=105` — its
range reaches both the stop and the target, so the outcome depends entirely on the path
assumption.

| `intrabar_path` | Path walked | Outcome | Fill price | P/L |
|---|---|---|---|---|
| `open_high_low_close` | 100 → 110 → 90 → 105 | TP hit first | 108.0 | **+8.00** |
| `open_low_high_close` | 100 → 90 → 110 → 105 | SL hit first | 95.0 | **\u22125.00** |
| `pessimistic` (default, long position) | same as `open_low_high_close` | SL hit first | 95.0 | **\u22125.00** |

`tests/test_engine_intrabar_path.py` must assert all three rows exactly. This is a
small, fast test — it only needs the one bar above, not the full 20-bar fixture.

---

## 7. Metrics (exact formulas — don't leave these to interpretation)

Implement in `engine/metrics.py`, each with its own unit test against a hand-calculated
value:

- **Total return**: `(final_equity / initial_equity) - 1`
- **Sharpe ratio**: mean(period returns) / stdev(period returns) × sqrt(annualization
  factor). Annualization factor depends on bar timeframe — pass it as an explicit
  parameter, never hardcode it:

  | Bar timeframe | Annualization factor |
  |---|---|
  | Daily | 252 |
  | Hourly | 252 × 24 = 6048 |
  | 15-minute | 252 × 24 × 4 = 24192 |
  | 1-minute | 252 × 24 × 60 = 362880 |

  Assume risk-free rate = 0 for Phase 1.
- **Max drawdown**: largest peak-to-trough decline in the equity curve, as a percentage.
- **Win rate**: winning trades / total trades.
- **Profit factor**: gross profit / gross loss (absolute value).

---

## 8. Ticket backlog (build in this order — one Claude Code session per ticket)

Each ticket should end with passing tests, no regressions in earlier tests, type hints
on public functions, and a one-line docstring per public function/class.

1. **Project scaffolding** — repo structure above, `pyproject.toml`, empty modules,
   pytest configured and running (even with zero real tests).
2. **Core types** — `Bar`, `Order`, `Position`, `State` dataclasses exactly as in
   Section 3, with construction/validation unit tests.
3. **Data loader** — `load_ohlcv()` per Section 4, tested against a small fixture CSV
   including at least one malformed-input test (missing column, NaN).
4. **Strategy base + buy-and-hold** — `Strategy` ABC, plus a trivial reference strategy
   that buys on the first bar and holds — used to sanity-check the engine loop itself
   before adding crossover logic.
5. **Core engine loop (v0)** — bar-by-bar loop, immediate fill at signal bar, zero cost
   model, tested against the buy-and-hold strategy (equity should just track price).
6. **MA crossover strategy + known-answer test** — implement `ma_crossover.py` and the
   fixture/test described in Section 6, using the v0 fill rule.
7. **Next-bar-open fill timing** — change the engine's fill rule to the default in
   Section 5, and update the known-answer test's expected values accordingly.
8. **Cost model** — pluggable commission/slippage functions in `costs.py`, applied
   during fills; extend the known-answer test with a non-zero-cost assertion.
9. **Intrabar path resolution** — implement the `intrabar_path` parameter and rule from
   Section 5.1, defaulting to `"pessimistic"`; pass the known-answer test in Section 6.1
   for all three path settings.
10. **Metrics module** — implement all formulas from Section 7, each tested against a
   hand-calculated value on the known-answer dataset.
11. **CLI** — `run-backtest --data <path> --symbol <sym> --strategy <module:Class>
    --output results.json`, wiring loader → engine → metrics → JSON output. Output
    schema (fields, not just "a JSON file"):

    ```json
    {
      "symbol": "EURUSD",
      "final_equity": 10004.00,
      "metrics": {
        "total_return": 0.0004,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 1.0,
        "profit_factor": null
      },
      "trades": [
        {"timestamp": "2024-01-05T00:00:00", "action": "BUY", "quantity": 1, "price": 11.0, "tag": null},
        {"timestamp": "2024-01-11T00:00:00", "action": "CLOSE", "quantity": 1, "price": 13.0, "tag": null}
      ],
      "equity_curve": [{"timestamp": "2024-01-01T00:00:00", "equity": 10000.0}]
    }
    ```
12. **Smoke test wrapper** — a separate function/CLI flag that runs the strategy on
    just the last N bars with a timeout, catching and reporting exceptions, per the
    architecture doc's Section 6 (Smoke testing).
13. **MT5 data connector** — `load_ohlcv_from_mt5()` per Section 4a, plus the
    `mt5-fetch` CLI command for fetching and displaying a range. Independent of
    tickets 1–12's correctness chain — can be built any time after ticket 2 (Core
    types), since it only needs `Bar` to exist. Tested with a mocked MT5 API, not a
    live terminal.

---

## 9. Handoff note for Phase 2 (and Phase 3)

Once ticket 12 passes, this library is the thing Phase 2 wraps — not rewrites. The web
app calls the same `load_ohlcv()` → `BacktestEngine` → `metrics` functions; sandboxing
wraps the strategy execution step; the MQL/Pine adapters produce objects satisfying the
same `Strategy` interface from Section 3. No part of this core should need to change
shape to support that — if it does, that's a signal the interface in Section 3 was
under-specified and needs revisiting before Phase 2 starts.

**Phase 2 additions that build on this library without changing it** (see architecture
doc Sections 8.1/8.2):
- **Walk-forward and parameter-sweep runs** — an orchestration layer that calls the
  Phase 1 CLI/`run()` path repeatedly over rolling in/out-of-sample windows or a
  parameter grid, aggregating one results row per run. No engine or interface changes.
- **Results persistence** — ticket 11's CLI already writes one JSON file per run
  (Section 8 schema); Phase 2 moves this into a database table keyed by strategy
  version + data version + parameters, so runs become queryable and comparable instead
  of living as loose files.

**Forex-specific account mechanics (after ticket 13)**: swap/rollover, margin calls,
and weekend-gap handling extend `costs.py` and the engine's account-state tracking —
see architecture doc Section 7.2a. Sequence this right after the MT5 connector
(ticket 13) lands, since that's what supplies real forex data — actual gaps and swap
rates — to validate against.

**Phase 3 (future, MQL-only)**: true tick-data replay, as scoped in Section 5.1 — a
separate data source and execution mode that removes the intrabar-path assumption
entirely for MQL/generic-code strategies. Not started until the OHLC-based engine and
its adapters are already trusted in production, and never applies to Pine Script.
