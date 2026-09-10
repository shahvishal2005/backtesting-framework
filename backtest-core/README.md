# backtest-core

Phase 1 backtesting engine — see `../PHASE1_BUILD_SPEC.md` for the full spec and ticket
backlog, and `../Backtesting_Framework_Architecture.docx` for the overall multi-language
platform architecture this phase feeds into.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows git-bash; use .venv/bin/activate on Linux/Mac
pip install -e ".[dev]"
pytest
```
