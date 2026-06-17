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

import json

import app_analytics
import news_risk_monitor as nrm
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
        news_path: Path = Path("crypto_news.jsonl"),
        news_provider: Optional[Callable[[], list]] = None,
        broker_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.config = config or (load_config(config_path) if config_path else default_config())
        self.state_path = Path(state_path)
        self.history_path = Path(history_path)
        self.stop_trading_path = Path(stop_trading_path)
        self.news_path = Path(news_path)
        self._price_provider = price_provider or self._default_price_provider
        self._news_provider = news_provider or self._default_news_provider
        self._broker_factory = broker_factory
        self._broker = None
        self._broker_error: Optional[str] = None

    # --- paper broker (only built when live_paper is on) ----------------------
    def _get_broker(self):
        if self._broker is not None:
            return self._broker
        try:
            if self._broker_factory is not None:
                self._broker = self._broker_factory()
            else:
                from alpaca_paper_broker import AlpacaPaperBroker
                self._broker = AlpacaPaperBroker.from_env()
            self._broker_error = None
        except Exception as e:  # missing keys / network — surfaced to the UI, never crashes
            self._broker = None
            self._broker_error = str(e)
        return self._broker

    def _paper_active(self) -> bool:
        # Paper is fake money via a paper-only endpoint, so it does NOT depend on the global
        # STOP_TRADING switch (which guards real money / the retired Coinbase bot).
        return bool(self.config.live_paper)

    def _current_portfolio(self) -> Portfolio:
        """Source of truth: the Alpaca paper account when paper is active, else local state.
        In paper mode we track ONLY our basket positions (ignore the paper account's house cash)."""
        if self._paper_active():
            broker = self._get_broker()
            if broker is not None:
                try:
                    snap = broker.account_snapshot()
                    basket = {s: float(snap["holdings"].get(s, 0.0)) for s in self.config.weights}
                    return Portfolio(holdings=basket, cash=0.0)
                except Exception as e:
                    self._broker_error = str(e)
        return store.load_portfolio(self.state_path)

    # --- prices ---------------------------------------------------------------
    def _default_price_provider(self) -> Dict[str, float]:
        return ps.latest_prices_from_csvs(self.config.price_csvs)

    def prices(self) -> Dict[str, float]:
        return self._price_provider()

    # --- news (advisory + risk only; never a signal) --------------------------
    def _default_news_provider(self, max_items: int = 1500) -> list:
        """Read the most recent news rows from the local JSONL (tail). Empty if absent."""
        if not self.news_path.exists():
            return []
        lines = self.news_path.read_text().splitlines()[-max_items:]
        out = []
        for ln in lines:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
        return out

    def get_news_alerts(self) -> Dict[str, Any]:
        items = self._news_provider()
        return nrm.scan_news(items, watch_symbols=list(self.config.weights.keys()))

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
        paper = self._paper_active()
        if paper:
            self._get_broker()  # warm + capture any connection error for the UI
        pf = self._current_portfolio()
        prices = self.prices()
        priced = {s: pf.holdings.get(s, 0.0) * prices[s] for s in prices}
        return {
            "mode": "paper" if paper else "simulate",
            "stop_trading_armed": self.stop_trading_path.exists(),
            "live_enabled": False,  # real-money live is never enabled here
            "broker_connected": bool(paper and self._broker is not None),
            "broker_error": self._broker_error if paper else None,
            "portfolio_value": round(pf.value(prices), 4),
            "cash": round(pf.cash, 4),
            "holdings_units": {s: round(u, 8) for s, u in pf.holdings.items()},
            "holdings_value": {s: round(v, 4) for s, v in priced.items()},
            "prices": {s: round(p, 4) for s, p in prices.items()},
        }

    def get_plan(self, contribution: Optional[float] = None) -> Dict[str, Any]:
        return ps.build_plan(self._current_portfolio(), self.prices(), self.config,
                             contribution=contribution)

    def get_history(self) -> list:
        return store.load_history(self.history_path)

    def get_equity_curve(self) -> Dict[str, Any]:
        return app_analytics.equity_curve(store.load_history(self.history_path))

    # --- action ---------------------------------------------------------------
    def approve_plan_paper(self, contribution: Optional[float] = None) -> Dict[str, Any]:
        """Operator approved the plan. Routes to the Alpaca PAPER account when paper is active
        (live_paper on + STOP_TRADING absent + broker reachable), else SIMULATES locally.
        Real-money LIVE is never reached here. Logs the period for the equity curve."""
        prices = self.prices()
        pf = self._current_portfolio()
        plan = ps.build_plan(pf, prices, self.config, contribution=contribution)
        contrib = float(plan.get("contribution", 0.0))

        if self._paper_active() and self._get_broker() is not None:
            result, _ = paper_executor.execute_plan(
                pf, plan, prices, self.config, approved=True, mode="paper",
                stop_trading_path=self.stop_trading_path, broker=self._broker,
            )
            # broker is source of truth; record contribution + post-submit basket value
            after = self._current_portfolio()
            value = round(after.value(prices), 4)
            store.append_history({"event": "paper_fill", "plan": plan,
                                  "result": {**result, "portfolio_value": value}},
                                 self.history_path)
            return {**result, "portfolio_value": value}

        # simulated fallback (default until paper is enabled)
        result, new_pf = paper_executor.execute_plan(
            pf, plan, prices, self.config, approved=True, mode="simulate",
            stop_trading_path=self.stop_trading_path,
        )
        store.save_portfolio(new_pf, self.state_path)
        store.append_history({"event": "paper_fill", "plan": plan, "result": result},
                             self.history_path)
        return result
