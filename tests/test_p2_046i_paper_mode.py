"""P2-046I — app_api paper-mode wiring (fake broker, no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
from app_api import AccumulatorAPI

PRICES = {"SPY": 50.0, "GLD": 20.0, "SLV": 10.0, "QQQ": 40.0, "BTC": 1000.0}


class FakeBroker:
    def __init__(self, positions=None):
        self.submitted = []
        self.positions = dict(positions or {})  # root -> qty
        self.closed = False

    def submit_orders(self, orders):
        self.submitted.extend(orders)
        return [{"symbol": o.symbol, "side": o.side, "dollars": o.dollars,
                 "order_id": "ord", "status": "accepted"} for o in orders]

    def account_snapshot(self):
        return {"cash": 100000.0, "equity": 100000.0, "holdings": dict(self.positions)}

    def close_all(self):
        self.closed = True
        self.positions = {}


def make_api(tmp_path, *, live_paper, broker=None, factory=None):
    c = app_config.default_config()
    c.live_paper = live_paper
    return AccumulatorAPI(
        config=c, state_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl",
        price_provider=lambda: dict(PRICES),
        stop_trading_path=tmp_path / "STOP_absent",
        broker_factory=factory or (lambda: broker),
    )


def test_simulate_mode_when_live_paper_off(tmp_path):
    api = make_api(tmp_path, live_paper=False, broker=FakeBroker())
    st = api.get_status()
    assert st["mode"] == "simulate" and st["broker_connected"] is False


def test_paper_mode_uses_broker_positions_as_truth(tmp_path):
    broker = FakeBroker(positions={"SPY": 2.0})  # 2 shares @ $50 = $100 basket value
    api = make_api(tmp_path, live_paper=True, broker=broker)
    st = api.get_status()
    assert st["mode"] == "paper" and st["broker_connected"] is True
    assert st["portfolio_value"] == 100.0          # ignores house cash, counts basket only
    assert st["holdings_units"]["SPY"] == 2.0


def test_paper_independent_of_stop_trading(tmp_path):
    # paper is fake money via a paper-only broker, so the old-bot STOP_TRADING switch does NOT
    # disable it (and the operator never has to remove STOP_TRADING to paper-trade).
    stop = tmp_path / "STOP_TRADING"
    stop.write_text("")
    c = app_config.default_config(); c.live_paper = True
    api = AccumulatorAPI(config=c, state_path=tmp_path / "s.json",
                         history_path=tmp_path / "h.jsonl", price_provider=lambda: dict(PRICES),
                         stop_trading_path=stop, broker_factory=lambda: FakeBroker())
    assert api.get_status()["mode"] == "paper"


def test_approve_in_paper_mode_submits_to_broker(tmp_path):
    broker = FakeBroker()
    api = make_api(tmp_path, live_paper=True, broker=broker)
    res = api.approve_plan_paper(contribution=100.0)
    assert res["mode"] == "broker_paper"
    assert len(broker.submitted) == 5          # one per basket asset
    assert res["authorizes_live"] is False
    assert len(api.get_history()) == 1         # logged for the equity curve


def test_broker_factory_failure_degrades_gracefully(tmp_path):
    def boom():
        raise RuntimeError("Paper keys not found")
    api = make_api(tmp_path, live_paper=True, factory=boom)
    st = api.get_status()
    # paper requested but broker unavailable -> reports error, still returns, no crash
    assert st["mode"] == "paper"
    assert st["broker_connected"] is False
    assert "Paper keys not found" in (st["broker_error"] or "")


def test_approve_falls_back_to_simulate_when_broker_unavailable(tmp_path):
    def boom():
        raise RuntimeError("no keys")
    api = make_api(tmp_path, live_paper=True, factory=boom)
    res = api.approve_plan_paper(contribution=100.0)
    assert res["mode"] == "simulate"  # safe fallback, no broker


def test_reset_paper_liquidates_and_clears(tmp_path):
    broker = FakeBroker(positions={"SPY": 2.0})
    api = make_api(tmp_path, live_paper=True, broker=broker)
    api.approve_plan_paper(contribution=100.0)  # create some history
    r = api.reset_paper()
    assert r["reset"] is True and broker.closed is True
    assert not (tmp_path / "h.jsonl").exists()  # history cleared


def test_reset_paper_refused_in_live(tmp_path):
    import app_config
    from app_api import AccumulatorAPI
    c = app_config.default_config(); c.live_trading_enabled = True  # live mode
    api = AccumulatorAPI(config=c, state_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl",
                         price_provider=lambda: dict(PRICES),
                         live_broker_factory=lambda: FakeBroker())
    try:
        api.reset_paper()
        assert False, "reset must be refused in live mode"
    except Exception as e:
        assert "paper mode" in str(e)
