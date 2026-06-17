"""P2-046L — Level-3 auto-invest scheduler logic (offline, no broker, no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
from app_api import AccumulatorAPI

PRICES = {"SPY": 50.0, "GLD": 20.0, "SLV": 10.0, "QQQ": 40.0, "BTC": 1000.0}
SAFE_NEWS = [{"date": "2026-06-17", "symbol": "SPY", "headline": "Markets drift higher"}]
RISK_NEWS = [{"date": "2026-06-17", "symbol": "BTC/USD", "headline": "Major exchange hacked, funds drained"}]


class FakeBroker:
    def __init__(self, cash=100000.0):
        self.cash = cash
        self.submitted = []

    def submit_orders(self, orders):
        self.submitted.extend(orders)
        return [{"symbol": o.symbol, "side": o.side, "dollars": o.dollars} for o in orders]

    def account_snapshot(self):
        return {"cash": self.cash, "equity": self.cash, "holdings": {}}


def make_api(tmp_path, *, auto, live, broker=None, news=SAFE_NEWS, contribution=100.0):
    c = app_config.default_config()
    c.auto_invest = auto
    c.live_trading_enabled = live
    c.contribution = contribution
    return AccumulatorAPI(
        config=c, state_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl",
        price_provider=lambda: dict(PRICES), news_provider=lambda: list(news),
        accumulator_stop_path=tmp_path / "ACC_STOP",
        live_broker_factory=lambda: (broker or FakeBroker()))


def test_auto_run_halted_by_kill_switch(tmp_path):
    api = make_api(tmp_path, auto=True, live=True)
    api.halt_live()
    r = api.auto_run()
    assert r["action"] == "halted"


def test_auto_run_pauses_on_risk_alert(tmp_path):
    api = make_api(tmp_path, auto=True, live=True, news=RISK_NEWS)
    r = api.auto_run()
    assert r["action"] == "paused_risk" and r["n_alerts"] >= 1
    # must NOT have traded into the catastrophe


def test_auto_run_notify_only_when_auto_off(tmp_path):
    api = make_api(tmp_path, auto=False, live=False)
    r = api.auto_run()
    assert r["action"] == "notify_only"


def test_auto_run_skips_when_underfunded(tmp_path):
    broker = FakeBroker(cash=10.0)  # < $100 contribution
    api = make_api(tmp_path, auto=True, live=True, broker=broker, contribution=100.0)
    r = api.auto_run()
    assert r["action"] == "skipped_funding" and not broker.submitted


def test_auto_run_executes_when_funded_and_clear(tmp_path):
    broker = FakeBroker(cash=100000.0)
    api = make_api(tmp_path, auto=True, live=True, broker=broker, contribution=10.0)
    r = api.auto_run()
    assert r["action"] == "executed_live" and r["n_fills"] == 5
    assert len(broker.submitted) == 5
    assert len(api.get_history()) == 1


def test_auto_run_risk_pause_takes_priority_over_execution(tmp_path):
    broker = FakeBroker(cash=100000.0)
    api = make_api(tmp_path, auto=True, live=True, broker=broker, news=RISK_NEWS)
    r = api.auto_run()
    assert r["action"] == "paused_risk"
    assert not broker.submitted  # risk pause prevents the trade
