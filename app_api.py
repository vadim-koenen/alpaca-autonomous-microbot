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
        live_broker_factory: Optional[Callable[[], Any]] = None,
        accumulator_stop_path: Path = Path("runtime/ACCUMULATOR_STOP"),
    ) -> None:
        self.config = config or (load_config(config_path) if config_path else default_config())
        self.state_path = Path(state_path)
        self.history_path = Path(history_path)
        self.stop_trading_path = Path(stop_trading_path)
        self.accumulator_stop_path = Path(accumulator_stop_path)
        self.news_path = Path(news_path)
        self._price_provider = price_provider or self._default_price_provider
        self._news_provider = news_provider or self._default_news_provider
        self._broker_factory = broker_factory
        self._live_broker_factory = live_broker_factory
        self._broker = None
        self._broker_error: Optional[str] = None

    # --- execution mode + brokers --------------------------------------------
    def _mode(self) -> str:
        if self.config.live_trading_enabled:
            return "live"
        if self.config.live_paper:
            return "paper"
        return "simulate"

    def _get_broker(self):
        """Build the broker for the ACTIVE mode (live or paper). Cached. Errors surfaced, not raised."""
        if self._broker is not None:
            return self._broker
        mode = self._mode()
        if mode == "simulate":
            return None
        try:
            if mode == "live":
                if self._live_broker_factory is not None:
                    self._broker = self._live_broker_factory()
                else:
                    from alpaca_live_broker import AlpacaLiveBroker
                    self._broker = AlpacaLiveBroker.from_env()
            else:  # paper
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
        return self._mode() == "paper"

    def _broker_active(self) -> bool:
        return self._mode() in ("paper", "live")

    def _current_portfolio(self) -> Portfolio:
        """Source of truth: the Alpaca account (paper or live) when a broker mode is active, else
        local state. We track ONLY our basket positions (ignore the account's house cash)."""
        if self._broker_active():
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
        mode = self._mode()
        broker_mode = self._broker_active()
        if broker_mode:
            self._get_broker()  # warm + capture any connection error for the UI
        pf = self._current_portfolio()
        prices = self.prices()
        priced = {s: pf.holdings.get(s, 0.0) * prices[s] for s in prices}
        return {
            "mode": mode,
            "stop_trading_armed": self.stop_trading_path.exists(),
            "accumulator_stopped": self.accumulator_stop_path.exists(),
            "live_enabled": mode == "live",
            "live_max_contribution": self.config.live_max_contribution,
            "broker_connected": bool(broker_mode and self._broker is not None),
            "broker_error": self._broker_error if broker_mode else None,
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

    def approve_plan_live(self, confirm: bool = False,
                          contribution: Optional[float] = None) -> Dict[str, Any]:
        """REAL MONEY. Submits the plan to the LIVE Alpaca account. Requires live mode enabled,
        an explicit confirm=True, a reachable live broker, and passes execute_plan's gates
        (dollar cap, ACCUMULATOR_STOP). Never auto-called; the operator triggers this deliberately."""
        if self._mode() != "live":
            raise paper_executor.ExecutionBlocked("live mode not enabled (config.live_trading_enabled)")
        broker = self._get_broker()
        if broker is None:
            raise paper_executor.ExecutionBlocked(self._broker_error or "live broker unavailable")
        prices = self.prices()
        pf = self._current_portfolio()
        plan = ps.build_plan(pf, prices, self.config, contribution=contribution)
        result, _ = paper_executor.execute_plan(
            pf, plan, prices, self.config, approved=True, mode="live",
            broker=broker, confirm_live=confirm,
            accumulator_stop_path=self.accumulator_stop_path,
        )
        value = round(self._current_portfolio().value(prices), 4)
        store.append_history({"event": "live_fill", "plan": plan,
                              "result": {**result, "portfolio_value": value}}, self.history_path)
        return {**result, "portfolio_value": value}

    # --- Level 3: scheduled auto-run -----------------------------------------
    def auto_run(self) -> Dict[str, Any]:
        """The scheduler entrypoint. Decides what to do this period and (if auto-invest is on)
        executes a live contribution — with safety rails. Returns an action summary for a
        notification. Order of checks is deliberate:
          1. ACCUMULATOR_STOP kill-switch -> do nothing.
          2. News RISK alert on the basket -> PAUSE (never trade into a catastrophe), notify.
          3. Not auto-invest -> notify-to-approve (Level 2).
          4. Insufficient account cash -> skip (never fail mid-order), notify to deposit.
          5. Otherwise -> execute the live contribution and notify the result.
        """
        if self.accumulator_stop_path.exists():
            return {"action": "halted", "message": "ACCUMULATOR_STOP present — no action taken."}

        news = self.get_news_alerts()
        if news.get("should_pause_recommended"):
            syms = ", ".join(sorted(news.get("alerts_by_symbol", {}).keys())) or "basket"
            return {"action": "paused_risk", "n_alerts": int(news.get("n_risk_alerts", 0)),
                    "message": f"PAUSED: {news.get('n_risk_alerts')} risk alert(s) ({syms}). "
                               "No auto-contribution — review before resuming."}

        auto_live = bool(self.config.auto_invest and self.config.live_trading_enabled)
        if not auto_live:
            plan = self.get_plan()
            return {"action": "notify_only",
                    "message": f"${plan['contribution']:.0f} contribution ready across "
                               f"{len(plan['orders'])} assets — open the app to approve."}

        broker = self._get_broker()
        if broker is None:
            return {"action": "error", "message": self._broker_error or "live broker unavailable"}
        try:
            cash = float(broker.account_snapshot().get("cash", 0.0))
        except Exception as e:
            return {"action": "error", "message": str(e)[:160]}
        if cash < float(self.config.contribution):
            return {"action": "skipped_funding", "cash": round(cash, 2),
                    "message": f"Insufficient cash (${cash:.2f}); deposit to auto-invest "
                               f"${self.config.contribution:.0f}."}
        try:
            res = self.approve_plan_live(confirm=True)
            return {"action": "executed_live", "n_fills": res.get("n_fills", 0),
                    "value": res.get("portfolio_value"),
                    "message": f"Auto-invested ${self.config.contribution:.0f}: "
                               f"{res.get('n_fills', 0)} live orders submitted."}
        except Exception as e:
            return {"action": "error", "message": str(e)[:160]}

    # --- safety controls ------------------------------------------------------
    def halt_live(self) -> Dict[str, Any]:
        """Create the dedicated accumulator kill-switch (blocks live execution immediately)."""
        self.accumulator_stop_path.parent.mkdir(parents=True, exist_ok=True)
        self.accumulator_stop_path.write_text("")
        return {"accumulator_stopped": True}

    def resume_live(self) -> Dict[str, Any]:
        if self.accumulator_stop_path.exists():
            self.accumulator_stop_path.unlink()
        return {"accumulator_stopped": False}
