"""SQLite-backed persistence: users/sessions (Stage C), results (Stage B), and
uploaded strategy projects (Stage E).

Every run is tagged with its code version (the installed backtest-core version) and
data version (a content hash of the uploaded file), so a stored result is traceable
back to exactly what produced it — Section 7.2's determinism requirement extended to
storage. Stage C adds user_id (every run belongs to exactly one user — runs are
private-per-user, the strategy code custody decision Section 9 calls for) and
elapsed_seconds (usage metering, tagged from day one per Section 9's other point).

Stage E's `strategies` table stores each uploaded project as an immutable version
(Section 5.7) — a re-upload under the same name gets the next version number rather
than overwriting anything, so a past backtest result could always be traced back to
the exact code that produced it, once execution is wired up in Phase 4.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "results.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    code_version TEXT NOT NULL,
    data_version TEXT NOT NULL,
    parameters TEXT NOT NULL,
    final_equity REAL NOT NULL,
    metrics TEXT NOT NULL,
    trades TEXT NOT NULL,
    equity_curve TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    manifest TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    UNIQUE(user_id, name, version)
);
"""

SESSION_TTL_DAYS = 7


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- users / sessions ---------------------------------------------------------------


def create_user(email: str, password_hash: str) -> int:
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, _now_iso()),
        )
        return cursor.lastrowid


def get_user_by_email(email: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_session(user_id: int, token: str) -> str:
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, _now_iso(), expires_at),
        )
    return expires_at


def get_session_user(token: str) -> dict | None:
    """Returns the user for a valid, unexpired session token, else None."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, _now_iso()),
        ).fetchone()
        return dict(row) if row else None


def delete_session(token: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --- runs (Stage B, now scoped per-user) ---------------------------------------------


def save_run(
    user_id: int,
    symbol: str,
    strategy_id: str,
    strategy_name: str,
    code_version: str,
    data_version: str,
    parameters: dict,
    final_equity: float,
    metrics: dict,
    trades: list,
    equity_curve: list,
    elapsed_seconds: float,
) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (
                user_id, created_at, symbol, strategy_id, strategy_name, code_version,
                data_version, parameters, final_equity, metrics, trades, equity_curve,
                elapsed_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                _now_iso(),
                symbol,
                strategy_id,
                strategy_name,
                code_version,
                data_version,
                json.dumps(parameters),
                final_equity,
                json.dumps(metrics),
                json.dumps(trades),
                json.dumps(equity_curve),
                elapsed_seconds,
            ),
        )
        return cursor.lastrowid


def list_runs(user_id: int, limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, symbol, strategy_name, code_version, data_version,
                   final_equity, parameters
            FROM runs WHERE user_id = ? ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        summaries = []
        for row in rows:
            summary = dict(row)
            params = json.loads(summary.pop("parameters"))
            summary["market"] = params.get("market")
            summaries.append(summary)
        return summaries


def get_run(run_id: int, user_id: int) -> dict | None:
    """Returns None both when the run doesn't exist and when it belongs to a
    different user — the caller can't distinguish "not found" from "not yours",
    which is the point: existence of another user's run shouldn't leak either way."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE id = ? AND user_id = ?", (run_id, user_id)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["parameters"] = json.loads(result["parameters"])
        result["metrics"] = json.loads(result["metrics"])
        result["trades"] = json.loads(result["trades"])
        result["equity_curve"] = json.loads(result["equity_curve"])
        return result


def usage_summary(user_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS job_count, COALESCE(SUM(elapsed_seconds), 0) AS total_seconds "
            "FROM runs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row)


# --- uploaded strategy projects (Stage E) --------------------------------------------


def next_strategy_version(user_id: int, name: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(version) AS max_version FROM strategies WHERE user_id = ? AND name = ?",
            (user_id, name),
        ).fetchone()
        return (row["max_version"] or 0) + 1


def save_strategy(
    user_id: int,
    name: str,
    version: int,
    content_hash: str,
    manifest: dict,
    storage_path: str,
) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO strategies (user_id, name, version, created_at, content_hash, manifest, storage_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, version, _now_iso(), content_hash, json.dumps(manifest), storage_path),
        )
        return cursor.lastrowid


def list_strategies(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, version, created_at, content_hash, manifest
            FROM strategies WHERE user_id = ? ORDER BY name, version DESC
            """,
            (user_id,),
        ).fetchall()
        results = []
        for row in rows:
            entry = dict(row)
            entry["manifest"] = json.loads(entry["manifest"])
            results.append(entry)
        return results


def get_strategy(strategy_id: int, user_id: int) -> dict | None:
    """Same not-found/not-yours non-distinction as get_run — see its docstring."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM strategies WHERE id = ? AND user_id = ?", (strategy_id, user_id)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["manifest"] = json.loads(result["manifest"])
        return result
