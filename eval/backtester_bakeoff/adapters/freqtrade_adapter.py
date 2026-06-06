"""Adapter for the Freqtrade backtesting engine."""
from __future__ import annotations
from pathlib import Path
import importlib.util

class FreqtradeAdapter:
    def __init__(self, maker_fee: float = 0.006, taker_fee: float = 0.008):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.engine_name = "freqtrade"
        self.available = importlib.util.find_spec("freqtrade") is not None

    def run_backtest(self, ohlcv_path: Path) -> dict:
        if not self.available:
            return {"engine": self.engine_name, "status": "blocked_dependency_install_required"}
        return {"engine": self.engine_name, "status": "not_implemented_yet"}

    def evaluate_fidelity(self, live_cycles: list) -> dict:
        return {
            "engine": self.engine_name,
            "engine_available": self.available,
            "ran_full_50_cycle_eval": False,
            "verdict": "blocked_missing_dependencies" if not self.available else "pending"
        }
