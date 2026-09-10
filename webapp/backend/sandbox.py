"""Runs the strategy-execution step of a backtest in an isolated subprocess (Stage D).

Real process isolation, not the Python-thread timeout Phase 1 ticket 12's
run_smoke_test() uses — a subprocess can actually be killed on timeout; a thread
can't, which that function's own docstring already flags as a known limitation.
subprocess.run(..., timeout=...) kills the child and waits for it before re-raising,
giving a genuine guarantee the parent process gets control back.

Known gaps versus the full container-per-job plan (PHASE2_BUILD_SPEC.md Stage D): no
memory cap, no CPU cap, no network isolation — none of those are straightforward to
enforce for a plain OS process on Windows without Docker or Job Objects. Acceptable
for now because only the two trusted, built-in reference strategies ever run here —
Stage E (real user-submitted code) needs the container-based version before it can
safely go live, not this one.
"""

import json
import subprocess
import sys
from pathlib import Path

WORKER_SCRIPT = Path(__file__).parent / "sandbox_worker.py"
DEFAULT_TIMEOUT_SECONDS = 30


class SandboxTimeoutError(Exception):
    pass


class SandboxError(Exception):
    pass


def run_sandboxed(
    strategy_id: str,
    bars_payload: list[dict],
    initial_cash: float,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Runs sandbox_worker.py as a child process with the given job, and returns its
    parsed JSON result. Raises SandboxTimeoutError if it doesn't finish in time (the
    child is killed either way — subprocess.run guarantees this), or SandboxError if
    it exits non-zero for any other reason."""
    job = json.dumps({"strategy_id": strategy_id, "initial_cash": initial_cash, "bars": bars_payload})

    try:
        completed = subprocess.run(
            [sys.executable, str(WORKER_SCRIPT)],
            input=job,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxTimeoutError(f"strategy execution exceeded {timeout_seconds}s") from exc

    if completed.returncode != 0:
        try:
            error = json.loads(completed.stdout)["error"]
        except (json.JSONDecodeError, KeyError):
            error = completed.stderr.strip() or "unknown sandbox failure"
        raise SandboxError(error)

    return json.loads(completed.stdout)
