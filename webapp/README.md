# Backtest Core — Web UI (Phase 2, Stage A)

A thin web wrapper around `backtest-core` — no strategy upload, no sandboxing yet
(that's Stage D/E). Only the two existing reference strategies (`buy_and_hold`,
`ma_crossover`) are selectable. Calls the exact same `load_ohlcv()` -> `BacktestEngine`
-> `metrics` functions the CLI does.

## Run it

```bash
cd webapp/backend
python -m venv .venv
source .venv/Scripts/activate   # Windows git-bash; .venv/bin/activate on Linux/Mac
pip install -e "../../backtest-core"
pip install -e .
uvicorn main:app --reload
```

Then open http://127.0.0.1:8000 in a browser.

## Layout

```
webapp/
  backend/    FastAPI app (main.py) — wraps backtest-core, serves the frontend as static files
  frontend/   Plain HTML/CSS/JS — no build step
```
