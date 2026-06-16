#!/usr/bin/env python3
"""
app_api.py — P2-046E: the controller bridging UI <-> logic.

`AccumulatorAPI` exposes plain methods (get_status / get_plan / approve_plan_paper /
get_history / get_config) that return JSON-serializable dicts. The pywebview desktop shell
hands an instance to the web UI as `js_api`, so the front-end calls Python directly — no
HTTP server needed for a single-user local app. Every method is unit-testable headless by
injecting a `price_provider`.

GOVERNANCE: proposals + simulated local state only. No broker, no live authorization.
`approve_plan_paper` runs the paper executor in SIMULATE mode (no broker contact); the
real-broker path stays gated behind STOP_TRADING + a future approved step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

import paper_executor
import planner_service as ps
import portfolio_store as store
from allocator_engine import Portfolio
from app_config import AppConfig, default_config, load_config


class AccumulatorAPI:
    def __init__(
        self,
        *,
        config: Optional[AppConfig] = None,
        config_path: Optional[Path] = None,
        state_path: Path = store.DEFAULT_PATH,
        history_path: Path = Path("runtime/accumulator_history.jsonl"),
        price_provider: Optional[Callable[[], Dict[str, float]]] = None,
        stop_trading_path: Path = paper_executor.STOP_TRADING_PATH,
    ) -> None:
        self.config = config or (load_config(config_path) if config_path else default_config())
        self.state_path = Path(state_path)
        self.history_path = Path(history_path)
        self.stop_trading_path = Path(stop_trading_path)
        self._price_provider = price_provider or self._default_price_provider

    # --- prices ---------------------------------------------------------------
    def _default_price_provider(self) -> Dict[str, float]:
        return ps.latest_prices_from_csvs(self.config.price_csvs)

    def prices(self) -> Dict[str, float]:
        return self._price_provider()

    # --- read endpoints -------------------------------------------------------
    def get_config(self) -> Dict[str, Any]:
        return {
            "profile": self.config.profile,
            "weights": self.config.weights,
            "contribution": self.config.contribution,
            "cadence_days": self.config.cadence_days,
            "rebalance_band": self.config.rebalance_band,
            "allow_sell": self.config.allow_sell,
            "overlay_enabled": self.config.overlay_enabled,
        }

    def get_status(self) -> Dict[str, Any]:
        pf = store.load_portfolio(self.state_path)
        prices = self.prices()
        priced = {s: pf.holdings.get(s, 0.0) * prices[s] for s in prices}
        return {
            "stop_trading_armed": self.stop_trading_path.exists(),
            "live_enabled": False,
            "portfolio_value": round(pf.value(prices), 4),
            "cash": round(pf.cash, 4),
            "holdings_units": {s: round(u, 8) for s, u in pf.holdings.items()},
            "holdings_value": {s: round(v, 4) for s, v in priced.items()},
            "prices": {s: round(p, 4) for s, p in prices.items()},
        }

    def get_plan(self, contribution: Optional[float] = None) -> Dict[str, Any]:
        pf = store.load_portfolio(self.state_path)
        return ps.build_plan(pf, self.prices(), self.config, contribution=contribution)

    def get_history(self) -> list:
        return store.load_history(self.history_path)

    # --- action (simulate paper) ---------------------------------------------
    def approve_plan_paper(self, contribution: Optional[float] = None) -> Dict[str, Any]:
        """Operator approved: execute the current plan as SIMULATED paper fills, persist
        new state, and log it. No broker is contacted."""
        pf = store.load_portfolio(self.state_path)
        prices = self.prices()
        plan = ps.build_plan(pf, prices, self.config, contribution=contribution)
        result, new_pf = paper_executor.execute_plan(
            pf, plan, prices, self.config, approved=True, mode="simulate",
            stop_trading_path=self.stop_trading_path,
        )
        store.save_portfolio(new_pf, self.state_path)
        store.append_history({"event": "paper_fill", "plan": plan, "result": result},
                             self.history_path)
        return result
