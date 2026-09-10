"""Shared strategy registry — imported by both main.py and sandbox_worker.py.
Split out so the sandboxed worker process doesn't need to import FastAPI/main.py
(which would also try to mount the frontend static directory) just to know which
strategy classes exist.
"""

from strategies.buy_and_hold import BuyAndHold
from strategies.ma_crossover import MaCrossover

AVAILABLE_STRATEGIES = {
    "buy_and_hold": ("Buy & Hold", BuyAndHold),
    "ma_crossover": ("MA(2)/MA(4) Crossover", MaCrossover),
}
