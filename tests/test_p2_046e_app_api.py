"""P2-046E — paper executor + AccumulatorAPI bridge tests (offline, no broker)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paper_executor
import app_config
from allocator_engine import Portfolio
from app_api import AccumulatorAPI

PRICES = {"SPY": 50.0, "GLD": 20.0, "SLV": 10.0, "QQQ": 40.0, "BTC": 1000.0}


def price_provider():
    return dict(PRICES)


# --- paper_executor -----------------------------------------------------------

def test_executor_refuses_without_approval():
    c = app_config.default_config()
    plan = {"orders": [{"symbol": "SPY", "side": "BUY", "dollars": 35.0, "est_units": 0.7}]}
    try:
        paper_executor.execute_plan(Portfolio(), plan, PRICES, c, approved=False)
        assert False, "expected ExecutionBlocked"
    except paper_executor.ExecutionBlocked:
        pass


def test_executor_simulate_updates_portfolio():
    c = app_config.default_config()
    plan = {"orders": [{"symbol": "SPY", "side": "BUY", "dollars": 50.0, "est_units": 1.0}]}
    result, pf = paper_executor.execute_plan(Portfolio(cash=50.0), plan, PRICES, c,
                                             approved=True, mode="simulate")
    assert result["mode"] == "simulate" and result["authorizes_live"] is False
    assert pf.holdings["SPY"] > 0


def test_executor_broker_mode_blocked_when_stop_trading_present(tmp_path):
    c = app_config.default_config()
    stop = tmp_path / "STOP_TRADING"
    stop.write_text("")
    plan = {"orders": []}
    try:
        paper_executor.execute_plan(Portfolio(), plan, PRICES, c, approved=True,
                                    mode="broker", stop_trading_path=stop)
        assert False, "expected ExecutionBlocked"
    except paper_executor.ExecutionBlocked as e:
        assert "STOP_TRADING" in str(e)


def test_executor_broker_mode_blocked_even_without_stop_trading(tmp_path):
    # broker path stays gated until M4: live_paper defaults False, so it's refused even
    # when STOP_TRADING is absent.
    c = app_config.default_config()
    plan = {"orders": []}
    try:
        paper_executor.execute_plan(Portfolio(), plan, PRICES, c, approved=True,
                                    mode="broker", stop_trading_path=tmp_path / "absent")
        assert False, "expected ExecutionBlocked"
    except paper_executor.ExecutionBlocked as e:
        assert "live_paper" in str(e)


# --- AccumulatorAPI -----------------------------------------------------------

def make_api(tmp_path):
    return AccumulatorAPI(
        config=app_config.default_config(),
        state_path=tmp_path / "state.json",
        history_path=tmp_path / "hist.jsonl",
        price_provider=price_provider,
        stop_trading_path=tmp_path / "STOP_TRADING_absent",
    )


def test_api_status_empty(tmp_path):
    api = make_api(tmp_path)
    st = api.get_status()
    assert st["portfolio_value"] == 0.0
    assert st["live_enabled"] is False
    assert set(st["prices"]) == set(PRICES)


def test_api_get_plan_conservative(tmp_path):
    api = make_api(tmp_path)
    plan = api.get_plan(contribution=100.0)
    buys = {o["symbol"]: o["dollars"] for o in plan["orders"]}
    assert abs(buys["SPY"] - 35.0) < 1e-6 and abs(buys["BTC"] - 10.0) < 1e-6
    assert plan["authorizes_live"] is False


def test_api_approve_persists_state_and_history(tmp_path):
    api = make_api(tmp_path)
    res = api.approve_plan_paper(contribution=100.0)
    assert res["mode"] == "simulate" and res["n_fills"] == 5
    # state persisted -> next status shows value ~100 (minus cost)
    st = api.get_status()
    assert st["portfolio_value"] > 99.0
    # history recorded
    hist = api.get_history()
    assert len(hist) == 1 and hist[0]["event"] == "paper_fill"


def test_api_two_contributions_accumulate(tmp_path):
    api = make_api(tmp_path)
    api.approve_plan_paper(contribution=100.0)
    api.approve_plan_paper(contribution=100.0)
    st = api.get_status()
    assert st["portfolio_value"] > 198.0  # ~200 minus costs
    assert len(api.get_history()) == 2


def test_api_get_config(tmp_path):
    api = make_api(tmp_path)
    cfg = api.get_config()
    assert cfg["profile"] == "conservative" and cfg["overlay_enabled"] is False
