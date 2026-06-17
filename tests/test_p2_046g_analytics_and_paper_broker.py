"""P2-046G/H — equity-curve analytics + gated Alpaca paper-broker adapter tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_analytics
import app_config
import paper_executor
from allocator_engine import Order, Portfolio, BUY, SELL
from alpaca_paper_broker import AlpacaPaperBroker


# --- equity curve -------------------------------------------------------------

def _fill(contribution, value, t):
    return {"event": "paper_fill", "logged_utc": t,
            "plan": {"contribution": contribution}, "result": {"portfolio_value": value}}


def test_equity_curve_empty():
    ec = app_analytics.equity_curve([])
    assert ec["n_periods"] == 0 and ec["current_value"] == 0.0
    assert ec["total_return_pct"] == 0.0 and ec["authorizes_live"] is False


def test_equity_curve_accumulates_invested():
    hist = [_fill(100, 99.9, "t1"), _fill(100, 205.0, "t2")]
    ec = app_analytics.equity_curve(hist)
    assert ec["n_periods"] == 2
    assert ec["total_invested"] == 200.0
    assert ec["current_value"] == 205.0
    assert ec["total_gain"] == 5.0
    assert ec["total_return_pct"] == 2.5
    assert [p["invested"] for p in ec["points"]] == [100.0, 200.0]


def test_equity_curve_ignores_non_fill_events():
    hist = [{"event": "note"}, _fill(50, 50.0, "t1")]
    ec = app_analytics.equity_curve(hist)
    assert ec["n_periods"] == 1 and ec["total_invested"] == 50.0


# --- Alpaca paper broker (fake client, no network) ----------------------------

class FakeOrder:
    def __init__(self, oid):
        self.id = oid
        self.status = "accepted"


class FakeTradingClient:
    def __init__(self):
        self.submitted = []

    def submit_order(self, req):
        self.submitted.append(req)
        return FakeOrder(oid=f"ord-{len(self.submitted)}")


def test_paper_broker_submits_each_order():
    fake = FakeTradingClient()
    broker = AlpacaPaperBroker(fake)
    orders = [Order("SPY", BUY, 35.0, 0.5), Order("BTC/USD", BUY, 10.0, 0.0001)]
    fills = broker.submit_orders(orders)
    assert len(fake.submitted) == 2
    assert fills[0]["order_id"] == "ord-1" and fills[0]["status"] == "accepted"
    assert fills[1]["symbol"] == "BTC/USD"


def test_paper_broker_sets_tif_by_asset_class():
    fake = FakeTradingClient()
    broker = AlpacaPaperBroker(fake)
    broker.submit_orders([Order("SPY", BUY, 35.0, 0.5), Order("BTC/USD", BUY, 10.0, 0.0001)])
    # equity -> DAY, crypto -> GTC (string compare avoids importing enums)
    assert "DAY" in str(fake.submitted[0].time_in_force)
    assert "GTC" in str(fake.submitted[1].time_in_force)


# --- executor broker-mode gating ----------------------------------------------

PRICES = {"SPY": 50.0}
PLAN = {"contribution": 35.0, "orders": [{"symbol": "SPY", "side": "BUY",
                                          "dollars": 35.0, "est_units": 0.7}]}


def test_broker_mode_blocked_when_live_paper_disabled(tmp_path):
    c = app_config.default_config()  # live_paper defaults False
    try:
        paper_executor.execute_plan(Portfolio(), PLAN, PRICES, c, approved=True,
                                    mode="broker", broker=FakeTradingClient(),
                                    stop_trading_path=tmp_path / "absent")
        assert False, "expected ExecutionBlocked"
    except paper_executor.ExecutionBlocked as e:
        assert "live_paper" in str(e)


def test_broker_mode_blocked_without_broker(tmp_path):
    c = app_config.default_config()
    c.live_paper = True
    try:
        paper_executor.execute_plan(Portfolio(), PLAN, PRICES, c, approved=True,
                                    mode="broker", broker=None,
                                    stop_trading_path=tmp_path / "absent")
        assert False, "expected ExecutionBlocked"
    except paper_executor.ExecutionBlocked as e:
        assert "no broker" in str(e)


def test_broker_mode_blocked_when_stop_trading_present(tmp_path):
    c = app_config.default_config()
    c.live_paper = True
    stop = tmp_path / "STOP_TRADING"
    stop.write_text("")
    try:
        paper_executor.execute_plan(Portfolio(), PLAN, PRICES, c, approved=True,
                                    mode="broker", broker=AlpacaPaperBroker(FakeTradingClient()),
                                    stop_trading_path=stop)
        assert False, "expected ExecutionBlocked"
    except paper_executor.ExecutionBlocked as e:
        assert "STOP_TRADING" in str(e)


def test_broker_mode_executes_when_all_gates_open(tmp_path):
    # all gates satisfied -> submits to the (fake) paper account
    c = app_config.default_config()
    c.live_paper = True
    fake = FakeTradingClient()
    result, pf = paper_executor.execute_plan(
        Portfolio(), PLAN, PRICES, c, approved=True, mode="broker",
        broker=AlpacaPaperBroker(fake), stop_trading_path=tmp_path / "absent")
    assert result["mode"] == "broker_paper" and result["n_fills"] == 1
    assert result["authorizes_live"] is False
    assert len(fake.submitted) == 1
