"""FastAPI backend for Phase 2 Stages A/B/C — a thin web wrapper around backtest-core,
with results persisted to SQLite (Section 8.2) and scoped per authenticated user
(Section 9's strategy-code-custody decision: runs are private-per-user, never shared).

No strategy upload here: only the two pre-built reference strategies are selectable
via dropdown, and no user-submitted code executes. Sandboxing (Stage D) and custom
strategy upload (Stage E) come later, in that order, per the architecture doc's
Section 7.1/5.7 — this stage is intentionally safe to run with zero isolation.
"""

import hashlib
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from importlib.metadata import version as installed_version
from pathlib import Path

import auth
import db
from data.loader import load_ohlcv
from engine.engine import BacktestEngine
from engine.metrics import (
    ANNUALIZATION_FACTORS,
    max_drawdown,
    profit_factor,
    realized_pnls,
    sharpe_ratio,
    total_return,
    win_rate,
)
from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from strategies.buy_and_hold import BuyAndHold
from strategies.ma_crossover import MaCrossover

AVAILABLE_STRATEGIES = {
    "buy_and_hold": ("Buy & Hold", BuyAndHold),
    "ma_crossover": ("MA(2)/MA(4) Crossover", MaCrossover),
}

# Market/instrument categorization is UI metadata for organizing runs — the engine
# itself is instrument-agnostic OHLCV bar simulation regardless of what's picked here;
# selecting Options/Futures/Intraday/Swing doesn't currently change backtest behavior.
VALID_MARKETS = ("indian", "forex", "crypto")
VALID_INSTRUMENTS = ("stock", "options", "futures")
VALID_MODES = ("intraday", "swing")
FOREX_SYMBOLS = ("XAUUSD",)
CRYPTO_SYMBOLS = ("BTC", "ETH")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
CODE_VERSION = installed_version("backtest-core")


def _parse_date(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, f"{field_name} must be YYYY-MM-DD, got {value!r}") from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Backtest Core — Web UI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthRequest(BaseModel):
    email: str
    password: str


def require_user(
    session_token: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE_NAME),
) -> dict:
    if session_token is None:
        raise HTTPException(401, "not authenticated")
    user = db.get_session_user(session_token)
    if user is None:
        raise HTTPException(401, "session expired or invalid")
    return user


def _set_session_cookie(response: Response, user_id: int) -> None:
    token = auth.generate_session_token()
    db.create_session(user_id, token)
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=db.SESSION_TTL_DAYS * 86400,
        # secure=False: this app runs over plain http://127.0.0.1 in every stage so
        # far — flip to True the moment this is ever served over https.
    )


@app.post("/api/auth/register")
def register(body: AuthRequest, response: Response):
    email = body.email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise HTTPException(400, "enter a valid email address")
    if len(body.password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"password must be at least {auth.MIN_PASSWORD_LENGTH} characters")
    if db.get_user_by_email(email) is not None:
        raise HTTPException(400, "an account with that email already exists")

    user_id = db.create_user(email, auth.hash_password(body.password))
    _set_session_cookie(response, user_id)
    return {"email": email}


@app.post("/api/auth/login")
def login(body: AuthRequest, response: Response):
    email = body.email.strip().lower()
    user = db.get_user_by_email(email)
    if user is None or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "invalid email or password")
    _set_session_cookie(response, user["id"])
    return {"email": user["email"]}


@app.post("/api/auth/logout")
def logout(response: Response, session_token: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE_NAME)):
    if session_token:
        db.delete_session(session_token)
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(require_user)):
    return {"email": user["email"], "usage": db.usage_summary(user["id"])}


@app.get("/api/strategies")
def list_strategies():
    return [{"id": key, "name": name} for key, (name, _cls) in AVAILABLE_STRATEGIES.items()]


@app.get("/api/timeframes")
def list_timeframes():
    return sorted(ANNUALIZATION_FACTORS)


@app.post("/api/backtest")
async def run_backtest_endpoint(
    data_file: UploadFile,
    symbol: str = Form(...),
    strategy: str = Form(...),
    market: str = Form(...),
    instrument: str | None = Form(None),
    mode: str | None = Form(None),
    initial_cash: float = Form(10000.0),
    timeframe: str = Form("daily"),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    user: dict = Depends(require_user),
):
    if strategy not in AVAILABLE_STRATEGIES:
        raise HTTPException(400, f"unknown strategy {strategy!r}")
    if timeframe not in ANNUALIZATION_FACTORS:
        raise HTTPException(400, f"unknown timeframe {timeframe!r}")
    if market not in VALID_MARKETS:
        raise HTTPException(400, f"unknown market {market!r}; expected one of {VALID_MARKETS}")
    if instrument is not None and instrument not in VALID_INSTRUMENTS:
        raise HTTPException(400, f"unknown instrument {instrument!r}; expected one of {VALID_INSTRUMENTS}")
    if mode is not None and mode not in VALID_MODES:
        raise HTTPException(400, f"unknown mode {mode!r}; expected one of {VALID_MODES}")
    # server-side enforcement, not just a UI restriction — the frontend only offers
    # gold for forex and BTC/ETH for crypto, but the API shouldn't trust that alone
    if market == "forex" and symbol not in FOREX_SYMBOLS:
        raise HTTPException(400, f"forex is limited to {FOREX_SYMBOLS} for now, got {symbol!r}")
    if market == "crypto" and symbol not in CRYPTO_SYMBOLS:
        raise HTTPException(400, f"crypto is limited to {CRYPTO_SYMBOLS} for now, got {symbol!r}")

    start_dt = _parse_date(start_date, "start_date") if start_date else None
    end_dt = _parse_date(end_date, "end_date") if end_date else None
    if start_dt and end_dt and start_dt > end_dt:
        raise HTTPException(400, "start_date must be on or before end_date")

    data_bytes = await data_file.read()
    data_version = hashlib.sha256(data_bytes).hexdigest()[:16]

    suffix = Path(data_file.filename or "data.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data_bytes)
        tmp_path = tmp.name

    try:
        bars = load_ohlcv(tmp_path, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if start_dt or end_dt:
        end_dt_exclusive = end_dt + timedelta(days=1) if end_dt else None
        bars = [
            bar
            for bar in bars
            if (start_dt is None or bar.timestamp >= start_dt)
            and (end_dt_exclusive is None or bar.timestamp < end_dt_exclusive)
        ]
        if not bars:
            raise HTTPException(400, "no bars found in the selected date range")

    strategy_name, strategy_cls = AVAILABLE_STRATEGIES[strategy]
    started = time.monotonic()
    result = BacktestEngine(strategy_cls(), initial_cash=initial_cash).run(bars)
    elapsed_seconds = time.monotonic() - started

    pnls = realized_pnls(result.trades)
    equity_values = [point.equity for point in result.equity_curve]
    annualization_factor = ANNUALIZATION_FACTORS[timeframe]

    metrics_payload = {
        "total_return": total_return(initial_cash, result.final_equity),
        "sharpe": sharpe_ratio(equity_values, annualization_factor),
        "max_drawdown": max_drawdown(equity_values),
        "win_rate": win_rate(pnls),
        "profit_factor": profit_factor(pnls),
    }
    trades_payload = [
        {
            "timestamp": trade.timestamp.isoformat(),
            "action": trade.action.value,
            "quantity": trade.quantity,
            "price": trade.price,
            "tag": trade.tag,
        }
        for trade in result.trades
    ]
    equity_curve_payload = [
        {"timestamp": point.timestamp.isoformat(), "equity": point.equity}
        for point in result.equity_curve
    ]

    run_id = db.save_run(
        user_id=user["id"],
        symbol=symbol,
        strategy_id=strategy,
        strategy_name=strategy_name,
        code_version=CODE_VERSION,
        data_version=data_version,
        parameters={
            "initial_cash": initial_cash,
            "timeframe": timeframe,
            "market": market,
            "instrument": instrument,
            "mode": mode,
            "start_date": start_date,
            "end_date": end_date,
        },
        final_equity=result.final_equity,
        metrics=metrics_payload,
        trades=trades_payload,
        equity_curve=equity_curve_payload,
        elapsed_seconds=elapsed_seconds,
    )

    return {
        "run_id": run_id,
        "symbol": symbol,
        "market": market,
        "instrument": instrument,
        "mode": mode,
        "strategy_name": strategy_name,
        "code_version": CODE_VERSION,
        "data_version": data_version,
        "bars_used": len(bars),
        "elapsed_seconds": elapsed_seconds,
        "final_equity": result.final_equity,
        "metrics": metrics_payload,
        "trades": trades_payload,
        "equity_curve": equity_curve_payload,
    }


@app.get("/api/runs")
def list_runs_endpoint(limit: int = 50, user: dict = Depends(require_user)):
    return db.list_runs(user_id=user["id"], limit=limit)


@app.get("/api/runs/{run_id}")
def get_run_endpoint(run_id: int, user: dict = Depends(require_user)):
    run = db.get_run(run_id, user_id=user["id"])
    if run is None:
        raise HTTPException(404, f"no run with id {run_id}")
    return run


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
