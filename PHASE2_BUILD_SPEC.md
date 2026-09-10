# Backtest Web — Phase 2 Build Spec

**Scope**: wrap the Phase 1 `backtest-core` library in a web application — UI, results
persistence, multi-tenancy, sandboxing, and eventually the MQL/Pine adapters — per the
architecture document's Section 11.2 ("Phase 2 — wrap it").

**Ground rule carried over from Phase 1**: this spec wraps `backtest-core`, it does not
modify it. Every stage below calls the same `load_ohlcv()` → `BacktestEngine` →
`metrics` functions Phase 1 already proved correct. If a later stage ever needs the
core engine to change shape, that's a signal to stop and revisit
`PHASE1_BUILD_SPEC.md` Section 3 first, not to quietly diverge.

**Definition of done for the stages currently in scope (A–D)** — met: any number of
registered users can each upload data, run either reference strategy across
Indian/Forex/Crypto instruments over an arbitrary date range, see results rendered
correctly, and reload any of their own past runs from persisted history — with runs
strictly private per account, and the strategy-execution step itself running in an
isolated, genuinely-killable subprocess rather than in-process.

---

## 1. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Backend | FastAPI + uvicorn | async-friendly, automatic request validation, minimal boilerplate for a thin wrapper |
| Persistence | SQLite (stdlib `sqlite3`) | zero-ops, matches Phase 1's "no dependency until it's needed" philosophy; swap for Postgres when multi-tenancy (Stage C) needs concurrent writers |
| Frontend | Plain HTML/CSS/JS, no build step | Stage A is a thin wrapper, not a product — a build pipeline is premature until the UI's shape stabilizes |
| Charting | Chart.js (CDN, pinned `4.5.1`) | equity curve rendering |
| Date picker | flatpickr (CDN, pinned `4.6.13`) | themeable, no dependencies, replaces the native `<input type="date">` widget which can't be restyled |
| Dependency on Phase 1 | `backtest-core` installed editable (`pip install -e ../../backtest-core`) into the webapp's own venv | never vendor or copy engine code |

**CDN version note**: both Chart.js and flatpickr versions were verified to actually
resolve on cdnjs *before* being wired in (`curl -o /dev/null -w "%{http_code}"`) — a
guessed version number 404'd during Stage A and silently broke the whole results
panel. Always verify the exact version path exists before pinning it.

---

## 2. Repo structure

```
webapp/
  backend/
    main.py           # FastAPI app: routes, validation, wiring to backtest-core
    db.py             # SQLite persistence layer (users, sessions, runs)
    auth.py            # password hashing + session token helpers
    strategy_registry.py  # shared strategy id -> class map (main.py + sandbox_worker.py)
    sandbox.py             # subprocess-isolated strategy execution (Stage D)
    sandbox_worker.py      # the actual isolated subprocess entry point
    pyproject.toml
    data/              # gitignored — results.db lives here
  frontend/
    index.html
    styles.css          # black/gold design system, see Section 6
    app.js
  README.md
```

`.gitignore` excludes `/webapp/backend/data/` (precisely scoped — a blanket `data/`
pattern would have also matched `backtest-core/data/`, the real source package).

---

## 3. API reference (current, Stages A–C)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/register` | no | `{email, password}` JSON body → creates account, starts session |
| POST | `/api/auth/login` | no | `{email, password}` → starts session |
| POST | `/api/auth/logout` | no | invalidates the current session server-side, clears cookie |
| GET | `/api/auth/me` | yes | `{email, usage: {job_count, total_seconds}}`; 401 if not signed in — the frontend's own auth check on load |
| GET | `/api/strategies` | no | `[{id, name}]` — the reference strategies selectable via dropdown |
| GET | `/api/timeframes` | no | `["15min", "1min", "daily", "hourly"]` — for the Sharpe annualization factor |
| POST | `/api/backtest` | yes | Runs a backtest; see request/response shape below |
| GET | `/api/runs?limit=50` | yes | Summary list of **the current user's own** persisted runs, newest first |
| GET | `/api/runs/{id}` | yes | Full detail for one run — 404 (not 403) if it doesn't exist *or* belongs to another user, so existence can't be inferred either way |

**Auth**: session-cookie based, not JWT — `sessions` is a real table (`token`, `user_id`,
`expires_at`), so logout and revocation are just a `DELETE`, not a signing-key rotation.
Cookie is `httponly`, `samesite=lax`, 7-day TTL, **not yet `secure`** — this app has only
ever run over plain `http://127.0.0.1`; flip `secure=True` in `main.py`'s
`_set_session_cookie()` the moment this is served over HTTPS. Passwords are hashed with
`bcrypt` (min length 8 enforced server-side); every protected route requires a
`require_user` dependency that resolves the session cookie to a user or raises 401.

**POST `/api/backtest`** — multipart form:

| Field | Required | Notes |
|---|---|---|
| `data_file` | yes | CSV/Parquet, same contract as `load_ohlcv()` |
| `symbol` | yes | free text for `market=indian`; server-restricted for forex/crypto (below) |
| `strategy` | yes | one of `/api/strategies`' ids |
| `market` | yes | `indian` \| `forex` \| `crypto` |
| `instrument` | no | `stock` \| `options` \| `futures` — Indian market only |
| `mode` | no | `intraday` \| `swing` — only meaningful when `instrument=stock` |
| `initial_cash` | no, default 10000.0 | |
| `timeframe` | no, default `daily` | |
| `start_date` / `end_date` | no | `YYYY-MM-DD`; inclusive of the full end date; omit both to use the whole file |

Server-side validation (not just UI restriction — the API must not trust the frontend
alone): `market=forex` requires `symbol` in `("XAUUSD",)`; `market=crypto` requires
`symbol` in `("BTC", "ETH")`; `start_date` must be ≤ `end_date`; a date range that
excludes every bar in the file returns 400 rather than silently running on nothing.

Response includes `run_id`, `bars_used`, `elapsed_seconds`, `metrics` (`total_return`,
`sharpe`, `max_drawdown`, `win_rate`, `profit_factor` — same shape as the Phase 1 CLI's
JSON schema), `trades[]`, `equity_curve[]`. `elapsed_seconds` measures the full
sandboxed subprocess round-trip (Stage D), not just in-process compute — it's
meaningfully larger than Phase 1's own numbers because of that, by design.

**Sandbox error responses** (Stage D): `504` if the strategy execution subprocess
doesn't finish within `sandbox.DEFAULT_TIMEOUT_SECONDS` (30s) — the subprocess is
killed either way, this isn't a "maybe still running" timeout; `500` if the subprocess
exits non-zero for any other reason (a genuine strategy bug, for instance), with the
worker's own error message surfaced in `detail`.

**Honest limitation**: `instrument`/`mode` are metadata only. `backtest-core`'s engine
is generic OHLCV bar simulation — selecting Options, Futures, Intraday, or Swing
categorizes a run for display/history purposes but does not currently change how the
backtest computes (no options pricing, no futures margin/contract handling, no
session-aware intraday execution). This should be made explicit again wherever this
spec is read out of context, so it never gets silently assumed to be implemented.

---

## 4. Database schema (current, Stages B–C)

Three tables in `webapp/backend/data/results.db`:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,    -- bcrypt
    created_at TEXT NOT NULL
);

CREATE TABLE sessions (
    token TEXT PRIMARY KEY,          -- secrets.token_urlsafe(32)
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL         -- 7-day TTL from creation
);

CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),   -- every run belongs to exactly one user
    created_at TEXT NOT NULL,       -- ISO 8601 UTC
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    code_version TEXT NOT NULL,     -- installed backtest-core version (importlib.metadata)
    data_version TEXT NOT NULL,     -- sha256(upload bytes)[:16] — content-addressed, not filename-based
    parameters TEXT NOT NULL,       -- JSON: initial_cash, timeframe, market, instrument, mode, start_date, end_date
    final_equity REAL NOT NULL,
    metrics TEXT NOT NULL,          -- JSON
    trades TEXT NOT NULL,           -- JSON
    equity_curve TEXT NOT NULL,     -- JSON
    elapsed_seconds REAL NOT NULL   -- usage metering: wall-clock time of the engine.run() call
);
```

`code_version` + `data_version` together answer "did this run use the same code and
the same data as that one?" without needing to re-run anything — the traceability
requirement from the architecture doc's Section 7.2, extended to storage (Section 8.2).

`user_id` on `runs` is the concrete implementation of Section 9's strategy-code-custody
decision: **runs are private-per-user, never shared.** `db.get_run(run_id, user_id)`
filters by both columns in one query — a run that exists but belongs to someone else
returns `None`, identically to a run that doesn't exist at all, so the API can never be
used to enumerate or infer other users' activity.

`db.usage_summary(user_id)` derives `job_count` (`COUNT(*)`) and `total_seconds`
(`SUM(elapsed_seconds)`) directly from `runs` via query rather than maintaining a
separate running counter — avoids a second source of truth that could drift.

**Schema note**: this replaced Stage B's `runs` table outright (added `user_id`
NOT NULL and `elapsed_seconds` NOT NULL) rather than migrating it — the only existing
rows were synthetic test data from development, not anything worth preserving. A real
migration script will be needed the first time this schema changes after real user
data exists.

---

## 5. Frontend design system (Stages A–C)

**Palette** (CSS custom properties in `styles.css`): near-black background (`#060608`),
gold accent (`#d9b556` / bright `#f3cf72`), muted warm grays for secondary text, green
for positive, red for negative. `Space Grotesk` for display text, `JetBrains Mono` for
numeric/tabular data.

**Layout**: two-panel grid — Configure Run (left) / Results (right) — collapsing to a
single column under 860px. Panels are glass-morphic (`backdrop-filter: blur`, thin gold
border) over a faint animated grid background.

**Configure Run panel, top to bottom**:
1. Data file drop zone
2. **Market** selector (Indian / Forex / Crypto) with conditional sub-panel, visually
   grouped by a gold left-border accent:
   - **Indian**: Instrument (Stock/Options/Futures) → Mode (Intraday/Swing, shown only
     when Instrument = Stock) → free-text Symbol
   - **Forex**: Symbol locked to `XAUUSD — Gold` (disabled dropdown, single option)
   - **Crypto**: Symbol dropdown, BTC/ETH
3. Strategy, Initial Cash, Timeframe
4. Start Date / End Date — flatpickr calendars, cross-constrained (picking a start date
   sets the end picker's minimum and vice versa), themed to match the palette
5. Run button; error box below it for validation/request failures
6. Recent Runs — clickable history list, reloads a past run's full result without
   re-running anything

**Results panel**: run metadata line (date range + bar count actually used), 6 metric
cards, equity curve (Chart.js), trade log table.

**Auth gate (Stage C)**: a full-screen overlay (`backdrop-filter: blur` over the app)
shown whenever `GET /api/auth/me` returns 401 — blocks the entire app behind a single
Sign In / Create Account card until a session exists, toggled by one link rather than
two separate routes. On success the header's right side switches from nothing to the
signed-in user's email + a Logout button.

### Bugs found and fixed during Stages A–C (worth knowing before touching this code)

- **Chart.js / flatpickr CDN version pins**: a guessed version number 404'd silently;
  always verify the exact cdnjs path resolves before pinning.
- **`[hidden]` CSS specificity**: `.empty-state`/`.results` each set their own
  `display: flex`, which has the same specificity as the browser's built-in
  `[hidden] { display: none }` rule and loads later in the cascade — so toggling
  `el.hidden = true` in JS silently failed to hide them. Fixed with a global
  `[hidden] { display: none !important; }` safety net.
- **Native required-field validation is easy to miss**: a `placeholder` is not a
  `value` — an empty required field blocks form submission with a faint native
  tooltip and no JS error, no console output, nothing in a custom error box. Any
  required field should ship with a real default `value`, not just a placeholder.
- **CSS Grid `1fr` overflow**: grid items default to `min-width: auto`, so a track
  won't shrink below its content's intrinsic minimum width — the End Date field
  overflowed its column at desktop widths once flatpickr's alt-input became the
  content. Fixed with `min-width: 0` on `.field` and `width: 100%; min-width: 0` on
  `.text-input`. Standard fix for this whole class of grid/flex overflow bug.
- **Chart failure shouldn't blank the rest of the panel**: `renderChart()` used to run
  before `renderTrades()` with no isolation, so a Chart.js failure silently prevented
  the trade log from rendering too, even though its data was fine. Each render step
  in `renderResult()` now fails independently.

Verification method that caught most of these: Playwright driving the actual installed
Edge browser (`channel="msedge"`, headless) — full click-through of the real DOM, not
just `curl`/static review. Screenshots were taken *after* animations settle
(`wait_for_timeout` post-transition), since a mid-fade screenshot looks like a broken,
ghosted render and can be mistaken for a CSS bug.

---

## 6. Stage backlog

### Stage A — Minimal web UI — **DONE**
FastAPI backend wrapping `backtest-core` unchanged; upload data, pick strategy, run,
view results. No strategy upload, no sandboxing — only the two reference strategies
ever execute, so zero isolation is safe at this stage.

### Stage B — Results persistence — **DONE**
SQLite `runs` table; every run tagged with code/data version; run history UI with
click-to-reload.

### Stage C — Multi-tenancy & metering foundations — **DONE**
- User accounts: email/password, `bcrypt` hashing, DB-backed sessions (cookie, 7-day
  TTL, revocable via a plain `DELETE` — no JWT signing-key management)
- Usage metering tagged from day one: every run row carries `user_id` and
  `elapsed_seconds`; `job_count`/`total_seconds` derived from `runs` on demand rather
  than a separately-maintained counter
- Strategy code custody decision made concretely: runs are private-per-user.
  `db.get_run(run_id, user_id)` returns `None` identically whether a run doesn't exist
  or belongs to someone else — verified with two real accounts via curl, confirming
  cross-user access returns 404, not the other user's data
- **Deferred, not forgotten**: SQLite → Postgres migration. Still fine for one writer;
  revisit once concurrent writers are a real scenario (Stage F's closed beta is the
  natural trigger)

### Stage D — Sandboxing — **DONE (subprocess-based, not containers)**
Scope decision made explicitly, not by default: Docker wasn't installed on the dev
machine, and — more importantly — nothing untrusted actually executes yet (only the
two built-in reference strategies), so full container-per-job isolation would have
been infrastructure built ahead of the risk that justifies it. Built the lighter
version instead, upgradeable later:

- `sandbox_worker.py` — a standalone script that is the *only* place a strategy's
  `on_bar()` ever executes; reads a job (`strategy_id`, `bars`, `initial_cash`) as
  JSON on stdin, writes the result (or an error) as JSON on stdout
- `sandbox.py` — `run_sandboxed()` spawns that script via `subprocess.run(...,
  timeout=...)`. This is the real fix for the exact limitation Phase 1 ticket 12's
  `run_smoke_test()` docstring already flagged: a Python thread can't be
  force-terminated, but `subprocess.run`'s timeout genuinely kills the child process
  before re-raising — verified directly (a 0.0001s timeout against real work raised
  `SandboxTimeoutError` in 0.051s, confirming the child was actually killed, not just
  abandoned)
- `main.py`'s `/api/backtest` now serializes bars, calls `run_sandboxed()`, and
  reconstructs `Trade`/`EquityPoint` objects from the JSON result — everything
  downstream (metrics, persistence, response shape) is unchanged
- `elapsed_seconds` (Stage C's metering) now measures the full subprocess round-trip,
  which is honestly a better usage-metering number than pure in-process time was

**Known gaps versus the original container-based plan** (deliberately not built yet,
documented so they're not mistaken for done): no memory cap, no CPU cap, no network
isolation — none of those are straightforward to enforce for a plain OS process on
Windows without Docker or Windows Job Objects. **This subprocess version is not
sufficient for Stage E.** The moment Stage E lets anyone but you submit strategy code,
this needs to become the real container-per-job version — a stranger's code getting
process isolation and a timeout is not the same guarantee as memory/CPU/network caps.

### Stage E — Multi-file strategy submission
Accept a project (folder/zip/git URL) + manifest (entry point, language, dependencies,
parameters) per the architecture doc's Section 5.7. Vetted-package allowlist for
dependency installation. Immutable versioning per submission.

### Stage F — Closed beta, Python-only
Open access to a small set of real outside users on the pure-Python path — explicitly
*before* MQL/Pine support exists (Section 9's recommendation), to get product feedback
before investing months in translation work.

### Stage G — Walk-forward / parameter-sweep
Orchestration layer over the existing single-run engine — rolling in/out-of-sample
windows and parameter-grid sweeps, one results row per run. No engine changes needed.

### Stage H — Forex account mechanics
Swap/rollover cost model, margin/margin-call account-state tracking, weekend-gap
handling. Sequenced after the MT5 connector (Phase 1 ticket 13, already built), since
that's what supplies realistic forex data — real gaps, real swap rates — to validate
against.

### Stage I — MQL adapter
Decide Option A (headless terminal via Wine) vs. Option B (static translation to
Python) — a genuinely open decision, not pre-made. Validate against a golden set of
known-correct EA results.

### Stage J — Pine adapter
Reverse-engineer Pine's execution semantics closely enough to match TradingView's own
backtest numbers. Flagged in the architecture doc as the hardest part of the entire
project — built last, once everything else is trusted.

### Stage K — Phase 3 (later)
True tick-data replay for MQL/generic-code strategies, removing the intrabar-path
assumption entirely. Never applies to Pine. Not started until the OHLC-based engine and
its adapters are already trusted in production.
