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
import subprocess

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
        secrets_runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._secrets_runner = secrets_runner
        self.config = config or (load_config(config_path) if config_path else default_config())
        self._config_path = Path(config_path) if config_path else Path("app_config.json")
        self.state_path = Path(state_path)
        self.history_path = Path(history_path)
        self.stop_trading_path = Path(stop_trading_path)
        self.accumulator_stop_path = Path(accumulator_stop_path)
        self.news_path = Path(news_path)
        self._price_provider = price_provider or self._make_price_provider()
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
    def _make_price_provider(self) -> Callable[[], Dict[str, float]]:
        """Live Alpaca quotes (with CSV fallback) when config.live_prices, else CSV closes."""
        if getattr(self.config, "live_prices", True):
            try:
                from live_prices import LivePriceProvider
                return LivePriceProvider(list(self.config.weights), self.config.price_csvs)
            except Exception:
                pass
        return self._default_price_provider

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
    # --- settings / key entry (Keychain-backed) -------------------------------
    KEY_FIELDS = {"paper_api": "ALPACA_PAPER_API_KEY", "paper_secret": "ALPACA_PAPER_SECRET_KEY",
                  "live_api": "ALPACA_API_KEY", "live_secret": "ALPACA_SECRET_KEY"}

    def get_settings(self) -> Dict[str, Any]:
        """Settings + which credentials are present (booleans only — never the secret values)."""
        from secrets_store import get_credential
        keys = {field: bool(get_credential(var, runner=self._secrets_runner))
                for field, var in self.KEY_FIELDS.items()}
        return {
            "mode": self._mode(),
            "contribution": self.config.contribution,
            "adaptive_allocation": self.config.adaptive_allocation,
            "live_max_contribution": self.config.live_max_contribution,
            "auto_invest": self.config.auto_invest,
            "keys": keys,
        }

    def save_keys(self, paper_api: str = "", paper_secret: str = "",
                  live_api: str = "", live_secret: str = "") -> Dict[str, Any]:
        """Save provided (non-empty) keys to the macOS Keychain and force a reconnect.
        Values never logged. Returns which fields were saved."""
        from secrets_store import set_secret
        provided = {"paper_api": paper_api, "paper_secret": paper_secret,
                    "live_api": live_api, "live_secret": live_secret}
        saved = []
        for field, value in provided.items():
            if value and value.strip():
                if set_secret(self.KEY_FIELDS[field], value.strip(), runner=self._secrets_runner):
                    saved.append(field)
        self._broker = None          # rebuild broker with the new credentials on next call
        self._broker_error = None
        return {"saved": saved, "count": len(saved)}

    # --- honest research (educational, never a prediction) --------------------
    def _basket_index_series(self) -> Dict[str, float]:
        """A weighted 'basket index' close series (start=100) from the basket CSVs, for correlation."""
        import csv as _csv
        from pathlib import Path as _P
        per_asset = {}
        for sym, path in self.config.price_csvs.items():
            if not _P(path).exists():
                continue
            rows = {r["date"]: float(r["close"]) for r in _csv.DictReader(_P(path).read_text().splitlines())
                    if r.get("close")}
            if rows:
                per_asset[sym] = rows
        if not per_asset:
            return {}
        common = sorted(set.intersection(*(set(v) for v in per_asset.values())))
        w = self.config.weights
        wsum = sum(w.get(s, 0) for s in per_asset) or 1.0
        index = {}
        base = {s: per_asset[s][common[0]] for s in per_asset} if common else {}
        for d in common:
            val = sum((w.get(s, 0) / wsum) * (per_asset[s][d] / base[s]) for s in per_asset)
            index[d] = val * 100.0
        return index

    def research(self, symbol: str, years: int = 5) -> Dict[str, Any]:
        """Fetch a ticker's real history and return an honest briefing (no predictions)."""
        import research_assistant as ra
        from app_config import ASSET_NAMES
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "no_symbol", "is_recommendation": False}
        try:
            import fetch_alpaca_bars as fab
            recs = fab.fetch_daily(symbol if symbol not in ("BTC", "ETH", "SOL") else f"{symbol}/USD",
                                   years, adjustment="all")  # split/dividend-adjusted for accuracy
            asset_series = {str(r.get("date") or r.get("timestamp"))[:10]: float(r["close"])
                            for r in recs if r.get("close")}
        except Exception as e:
            return {"symbol": symbol, "error": f"fetch_failed: {str(e)[:120]}",
                    "is_recommendation": False, "disclaimer": ra.DISCLAIMER}
        name = ASSET_NAMES.get(symbol, symbol)
        return ra.research_asset(symbol, name, asset_series, self._basket_index_series())

    def get_presets(self) -> Dict[str, Any]:
        import capital_allocation as cap
        return {"current": self.config.preset, "available": cap.list_presets()}

    def set_preset(self, name: str) -> Dict[str, Any]:
        """Switch the allocation preset (preservation|income|growth) and persist it."""
        import capital_allocation as cap
        from app_config import save_config
        if name not in cap.PRESETS:
            raise ValueError(f"unknown preset '{name}'")
        self.config.preset = name
        save_config(self.config, self._config_path)
        return {"preset": name}

    def get_config(self) -> Dict[str, Any]:
        return {
            "profile": self.config.profile,
            "preset": self.config.preset,
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

    def _reinvest_cash(self) -> float:
        """Dividend + interest income to redeploy this run (DRIP). 0 unless reinvest is on, a broker
        is active, and the activities API returns income within the cadence window."""
        if not getattr(self.config, "reinvest_dividends", False) or not self._broker_active():
            return 0.0
        broker = self._get_broker()
        if broker is None or not hasattr(broker, "income_since"):
            return 0.0
        from datetime import datetime, timedelta, timezone
        after = (datetime.now(timezone.utc)
                 - timedelta(days=max(1, self.config.cadence_days))).strftime("%Y-%m-%d")
        try:
            return float(broker.income_since(after))
        except Exception:
            return 0.0

    def get_dashboard(self) -> Dict[str, Any]:
        """One call with everything the stupid-simple UI needs: total value, profit/loss ($ and %),
        today's move, the single biggest mover (leader) and drag (laggard), per-asset rows in plain
        English, and the value-over-time points. Honest: P&L comes from the broker when live/paper,
        else from contributions-vs-value in simulate."""
        from app_config import ASSET_NAMES
        prices = self.prices()
        mode = self._mode()
        ec = app_analytics.equity_curve(store.load_history(self.history_path))
        detail: Dict[str, Dict[str, Any]] = {}
        total_value = 0.0
        total_pl = 0.0
        today_pl = 0.0

        if self._broker_active() and self._get_broker() is not None:
            try:
                pos = self._broker.account_snapshot().get("positions", {})
            except Exception as e:
                self._broker_error = str(e)
                pos = {}
            for s in self.config.weights:
                d = pos.get(s)
                if d and d.get("market_value"):
                    detail[s] = {"value": round(d["market_value"], 2),
                                 "pl": round(d.get("total_pl", 0.0), 2),
                                 "today": round(d.get("today_pl", 0.0), 2),
                                 "plpc": round(d.get("plpc", 0.0) * 100, 2)}
            total_value = round(sum(d["value"] for d in detail.values()), 2)
            total_pl = round(sum(d["pl"] for d in detail.values()), 2)
            today_pl = round(sum(d["today"] for d in detail.values()), 2)
        else:
            pf = store.load_portfolio(self.state_path)
            for s, u in pf.holdings.items():
                if u:
                    v = u * prices.get(s, 0.0)
                    detail[s] = {"value": round(v, 2), "pl": 0.0, "today": 0.0, "plpc": 0.0}
            total_value = round(pf.value(prices), 2)
            total_pl = ec["total_gain"]  # value - contributions

        # 'Invested' = the broker's actual cost basis (value - unrealized P&L) when a broker is
        # active; falls back to logged contributions in simulate. Robust to history resets.
        if self._broker_active() and detail:
            invested = round(total_value - total_pl, 2)
        else:
            invested = ec["total_invested"]
        pl_pct = round((total_pl / invested * 100), 2) if invested > 0 else 0.0
        # leader / laggard: rank by the most relevant move (today if any moved, else total P&L)
        use_today = any(abs(d["today"]) > 0 for d in detail.values())
        key = (lambda kv: kv[1]["today"]) if use_today else (lambda kv: kv[1]["pl"])
        rows = sorted(detail.items(), key=key, reverse=True)

        def named(item):
            if not item:
                return None
            s, d = item
            return {"symbol": s, "name": ASSET_NAMES.get(s, s),
                    "amount": d["today"] if use_today else d["pl"], **d}

        leader = named(rows[0]) if rows and key(rows[0]) > 0 else None
        laggard = named(rows[-1]) if rows and key(rows[-1]) < 0 else None
        holdings = [{"symbol": s, "name": ASSET_NAMES.get(s, s), **d}
                    for s, d in sorted(detail.items(), key=lambda kv: kv[1]["value"], reverse=True)]

        return {
            "mode": mode,
            "broker_connected": bool(self._broker_active() and self._broker is not None),
            "broker_error": self._broker_error if self._broker_active() else None,
            "total_value": total_value,
            "total_pl": total_pl,
            "total_pl_pct": pl_pct,
            "today_pl": today_pl,
            "invested": invested,
            "direction": "up" if total_pl > 0.005 else ("down" if total_pl < -0.005 else "flat"),
            "leader": leader,
            "laggard": laggard,
            "holdings": holdings,
            "points": ec["points"],
            "authorizes_live": False,
        }

    # --- action ---------------------------------------------------------------
    def approve_plan_paper(self, contribution: Optional[float] = None) -> Dict[str, Any]:
        """Operator approved the plan. Routes to the Alpaca PAPER account when paper is active
        (live_paper on + STOP_TRADING absent + broker reachable), else SIMULATES locally.
        Real-money LIVE is never reached here. Logs the period for the equity curve."""
        prices = self.prices()
        pf = self._current_portfolio()
        plan = ps.build_plan(pf, prices, self.config, contribution=contribution,
                             extra_cash=self._reinvest_cash())
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
        plan = ps.build_plan(pf, prices, self.config, contribution=contribution,
                             extra_cash=self._reinvest_cash())
        result, _ = paper_executor.execute_plan(
            pf, plan, prices, self.config, approved=True, mode="live",
            broker=broker, confirm_live=confirm,
            accumulator_stop_path=self.accumulator_stop_path,
        )
        value = round(self._current_portfolio().value(prices), 4)
        store.append_history({"event": "live_fill", "plan": plan,
                              "result": {**result, "portfolio_value": value}}, self.history_path)
        return {**result, "portfolio_value": value}

    # --- proactive check-ins --------------------------------------------------
    def get_suggestions(self) -> Dict[str, Any]:
        """Assemble current state and return the prioritized 'today's suggested action' list."""
        import suggestion_engine as se
        from datetime import datetime, timezone

        prices = self.prices()
        pf = self._current_portfolio()
        plan = ps.build_plan(pf, prices, self.config)
        news = self.get_news_alerts()

        # days since last contribution (from history)
        days = None
        hist = store.load_history(self.history_path)
        stamps = [r.get("logged_utc") or r.get("result", {}).get("executed_utc")
                  for r in hist if r.get("event") in ("paper_fill", "live_fill")]
        stamps = [s for s in stamps if s]
        if stamps:
            try:
                last = max(datetime.fromisoformat(s.replace("Z", "+00:00")) for s in stamps)
                days = (datetime.now(timezone.utc) - last).days
            except Exception:
                days = None

        drift = plan.get("drift", {})
        max_drift = max((abs(v) for v in drift.values()), default=0.0)

        # live funding check (only meaningful in live mode)
        funded = None
        if self._mode() == "live" and self._get_broker() is not None:
            try:
                cash = float(self._broker.account_snapshot().get("cash", 0.0))
                funded = cash >= float(self.config.contribution)
            except Exception:
                funded = None

        # Financial context from the broker's actual cost basis (matches the dashboard hero exactly,
        # so the two never disagree). invested = current value - unrealized P&L.
        dash = self.get_dashboard()
        total_value = dash["total_value"]
        total_pl = dash["total_pl"]
        invested = round(total_value - total_pl, 2)
        plp = round(total_pl / invested * 100, 1) if invested > 0 else None
        assumed = {"preservation": 0.04, "income": 0.06, "growth": 0.08}.get(
            getattr(self.config, "preset", "income"), 0.06)
        cadence = max(1, self.config.cadence_days)
        state = {
            "mode": self._mode(),
            "total_value": total_value,
            "invested": invested,
            "total_pl_pct": plp,
            "contribution": self.config.contribution,
            "cadence_days": self.config.cadence_days,
            "periods_per_year": 365.0 / cadence,
            "assumed_return": assumed,
            "days_since_contribution": days,
            "reinvest_amount": self._reinvest_cash(),
            "max_drift": max_drift,
            "rebalance_band": self.config.rebalance_band,
            "risk_alerts": int(news.get("n_risk_alerts", 0)),
            "tier": plan.get("tier"),
            "funded": funded,
        }
        items = se.suggest(state)
        return {"top": items[0], "suggestions": items, "authorizes_live": False}

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

    def reset_paper(self) -> Dict[str, Any]:
        """Clean slate: liquidate the PAPER account and clear local history/state. Paper-only —
        refuses in live mode so it can never touch real money."""
        if self._mode() != "paper":
            raise paper_executor.ExecutionBlocked("reset_paper only allowed in paper mode")
        broker = self._get_broker()
        if broker is None:
            raise paper_executor.ExecutionBlocked(self._broker_error or "paper broker unavailable")
        broker.close_all()
        for p in (self.state_path, self.history_path):
            if Path(p).exists():
                Path(p).unlink()
        return {"reset": True, "message": "Paper account liquidated; local history cleared."}

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
