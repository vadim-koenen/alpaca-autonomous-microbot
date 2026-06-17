"""P2-046J/K — gated live execution + Level-2 notifications (offline, no broker, no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
import notifier
import paper_executor
from allocator_engine import Portfolio
from app_api import AccumulatorAPI

PRICES = {"SPY": 50.0, "GLD": 20.0, "SLV": 10.0, "QQQ": 40.0, "BTC": 1000.0}
PLAN = {"contribution": 10.0, "orders": [{"symbol": "SPY", "side": "BUY",
                                          "dollars": 3.5, "est_units": 0.07}]}


class FakeClient:
    def __init__(self):
        self.submitted = []

    def submit_order(self, req):
        self.submitted.append(req)
        return type("O", (), {"id": "x", "status": "accepted"})()

    def get_account(self):
        return type("A", (), {"cash": "100", "equity": "100"})()

    def get_all_positions(self):
        return []


class FakeBroker:
    def __init__(self):
        self.submitted = []

    def submit_orders(self, orders):
        self.submitted.extend(orders)
        return [{"symbol": o.symbol, "side": o.side, "dollars": o.dollars} for o in orders]

    def account_snapshot(self):
        return {"cash": 0.0, "equity": 0.0, "holdings": {}}


# --- live executor gates ------------------------------------------------------

def _live_cfg():
    c = app_config.default_config()
    c.live_trading_enabled = True
    return c


def test_live_blocked_when_disabled():
    c = app_config.default_config()  # live_trading_enabled False
    try:
        paper_executor.execute_plan(Portfolio(), PLAN, PRICES, c, approved=True,
                                    mode="live", broker=FakeBroker(), confirm_live=True)
        assert False
    except paper_executor.ExecutionBlocked as e:
        assert "live_trading_enabled" in str(e)


def test_live_blocked_without_confirm():
    try:
        paper_executor.execute_plan(Portfolio(), PLAN, PRICES, _live_cfg(), approved=True,
                                    mode="live", broker=FakeBroker(), confirm_live=False)
        assert False
    except paper_executor.ExecutionBlocked as e:
        assert "confirm_live" in str(e)


def test_live_blocked_over_cap():
    c = _live_cfg()
    c.live_max_contribution = 5.0
    plan = {"contribution": 10.0, "orders": []}  # 10 > 5 cap
    try:
        paper_executor.execute_plan(Portfolio(), plan, PRICES, c, approved=True,
                                    mode="live", broker=FakeBroker(), confirm_live=True)
        assert False
    except paper_executor.ExecutionBlocked as e:
        assert "cap" in str(e)


def test_live_blocked_by_accumulator_stop(tmp_path):
    stop = tmp_path / "ACCUMULATOR_STOP"
    stop.write_text("")
    try:
        paper_executor.execute_plan(Portfolio(), PLAN, PRICES, _live_cfg(), approved=True,
                                    mode="live", broker=FakeBroker(), confirm_live=True,
                                    accumulator_stop_path=stop)
        assert False
    except paper_executor.ExecutionBlocked as e:
        assert "ACCUMULATOR_STOP" in str(e)


def test_live_executes_when_all_gates_open(tmp_path):
    broker = FakeBroker()
    result, _ = paper_executor.execute_plan(
        Portfolio(), PLAN, PRICES, _live_cfg(), approved=True, mode="live",
        broker=broker, confirm_live=True, accumulator_stop_path=tmp_path / "absent")
    assert result["mode"] == "broker_live" and result["real_money"] is True
    assert len(broker.submitted) == 1


# --- app_api live wiring ------------------------------------------------------

def make_live_api(tmp_path, broker):
    c = _live_cfg()
    return AccumulatorAPI(config=c, state_path=tmp_path / "s.json",
                          history_path=tmp_path / "h.jsonl", price_provider=lambda: dict(PRICES),
                          accumulator_stop_path=tmp_path / "ACC_STOP",
                          live_broker_factory=lambda: broker)


def test_api_mode_is_live(tmp_path):
    api = make_live_api(tmp_path, FakeBroker())
    st = api.get_status()
    assert st["mode"] == "live" and st["live_enabled"] is True


def test_api_approve_live_requires_confirm(tmp_path):
    api = make_live_api(tmp_path, FakeBroker())
    try:
        api.approve_plan_live(confirm=False, contribution=10.0)
        assert False
    except paper_executor.ExecutionBlocked as e:
        assert "confirm_live" in str(e)


def test_api_approve_live_submits_with_confirm(tmp_path):
    broker = FakeBroker()
    api = make_live_api(tmp_path, broker)
    res = api.approve_plan_live(confirm=True, contribution=10.0)
    assert res["mode"] == "broker_live" and len(broker.submitted) == 5
    assert len(api.get_history()) == 1


def test_api_halt_and_resume_live(tmp_path):
    broker = FakeBroker()
    api = make_live_api(tmp_path, broker)
    api.halt_live()
    try:
        api.approve_plan_live(confirm=True, contribution=10.0)
        assert False, "halt should block"
    except paper_executor.ExecutionBlocked as e:
        assert "ACCUMULATOR_STOP" in str(e)
    api.resume_live()
    res = api.approve_plan_live(confirm=True, contribution=10.0)
    assert res["mode"] == "broker_live"


# --- notifier -----------------------------------------------------------------

def test_compose_weekly_message_no_alerts():
    plan = {"contribution": 10.0, "orders": [{}, {}, {}, {}, {}]}
    news = {"n_risk_alerts": 0, "alerts_by_symbol": {}}
    m = notifier.compose_weekly_message(plan, news)
    assert "$10" in m["message"] and "No risk alerts" in m["subtitle"]


def test_compose_weekly_message_with_alerts():
    plan = {"contribution": 10.0, "orders": [{}]}
    news = {"n_risk_alerts": 2, "alerts_by_symbol": {"BTC": 2}}
    m = notifier.compose_weekly_message(plan, news)
    assert "2 risk alert" in m["subtitle"] and "BTC" in m["subtitle"]


def test_macos_notify_uses_runner():
    calls = []
    ok = notifier.macos_notify("T", "M", subtitle="S", runner=lambda *a, **k: calls.append(a))
    assert ok is True and calls and "osascript" in calls[0][0]


def test_macos_notify_handles_failure():
    def boom(*a, **k):
        raise RuntimeError("no osascript")
    assert notifier.macos_notify("T", "M", runner=boom) is False
