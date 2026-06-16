"""P2-046D — app backend (config, portfolio store, planner service) tests."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
import planner_service as ps
import portfolio_store as store
from allocator_engine import Portfolio


# --- app_config ---------------------------------------------------------------

def test_default_config_is_conservative_and_valid():
    c = app_config.default_config()
    assert c.profile == "conservative"
    assert abs(sum(c.weights.values()) - 1.0) < 1e-9
    assert c.weights["SPY"] == 0.35 and c.weights["BTC"] == 0.10
    assert c.overlay_enabled is False  # P2-046A verdict baked in


def test_config_validate_rejects_bad_weights():
    c = app_config.AppConfig(weights={"A": 0.5, "B": 0.4})  # sums to 0.9
    try:
        c.validate()
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_config_roundtrip(tmp_path):
    c = app_config.default_config()
    c.contribution = 250.0
    p = tmp_path / "cfg.json"
    app_config.save_config(c, p)
    c2 = app_config.load_config(p)
    assert c2.contribution == 250.0 and c2.weights == c.weights


def test_load_config_missing_returns_default(tmp_path):
    c = app_config.load_config(tmp_path / "nope.json")
    assert c.profile == "conservative"


# --- portfolio_store ----------------------------------------------------------

def test_portfolio_roundtrip(tmp_path):
    p = Portfolio(holdings={"SPY": 1.5, "BTC": 0.01}, cash=12.34)
    path = tmp_path / "state.json"
    store.save_portfolio(p, path)
    p2 = store.load_portfolio(path)
    assert p2.holdings == p.holdings and abs(p2.cash - 12.34) < 1e-9


def test_load_portfolio_missing_is_empty(tmp_path):
    p = store.load_portfolio(tmp_path / "none.json")
    assert p.holdings == {} and p.cash == 0.0


def test_history_append_and_load(tmp_path):
    path = tmp_path / "hist.jsonl"
    store.append_history({"event": "plan", "value": 1}, path)
    store.append_history({"event": "fill", "value": 2}, path)
    rows = store.load_history(path)
    assert len(rows) == 2 and rows[0]["event"] == "plan" and "logged_utc" in rows[1]


# --- planner_service ----------------------------------------------------------

PRICES = {"SPY": 50.0, "GLD": 20.0, "SLV": 10.0, "QQQ": 40.0, "BTC": 1000.0}


def test_build_plan_empty_portfolio_deploys_by_target():
    c = app_config.default_config()
    c.contribution = 100.0
    plan = ps.build_plan(Portfolio(), PRICES, c)
    buys = {o["symbol"]: o["dollars"] for o in plan["orders"]}
    # conservative weights -> SPY gets the most ($35), BTC the least ($10)
    assert abs(buys["SPY"] - 35.0) < 1e-6
    assert abs(buys["BTC"] - 10.0) < 1e-6
    assert plan["authorizes_live"] is False
    assert abs(sum(buys.values()) - 100.0) < 1e-6


def test_build_plan_reports_drift():
    c = app_config.default_config()
    p = Portfolio(holdings={"BTC": 1.0})  # all BTC, hugely overweight vs 10% target
    plan = ps.build_plan(p, PRICES, c, contribution=100.0)
    assert plan["drift"]["BTC"] > 0   # overweight
    assert plan["drift"]["SPY"] < 0   # underweight
    # contribution-funded: new money buys underweights, not BTC
    btc_buys = [o for o in plan["orders"] if o["symbol"] == "BTC" and o["side"] == "BUY"]
    assert not btc_buys


def test_build_plan_only_uses_priced_symbols():
    c = app_config.default_config()
    partial = {"SPY": 50.0, "GLD": 20.0}  # missing the rest
    plan = ps.build_plan(Portfolio(), partial, c, contribution=100.0)
    syms = {o["symbol"] for o in plan["orders"]}
    assert syms <= {"SPY", "GLD"}
    # weights renormalized across the available pair
    assert abs(sum(plan["target_weights"].values()) - 1.0) < 1e-6


def test_render_plan_text_runs():
    c = app_config.default_config()
    plan = ps.build_plan(Portfolio(), PRICES, c, contribution=100.0)
    txt = ps.render_plan_text(plan)
    assert "Accumulator plan" in txt and "Proposed orders" in txt


def test_latest_prices_from_csvs(tmp_path):
    csvp = tmp_path / "X.csv"
    csvp.write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,10,1\n2024-01-02,1,1,1,20,1\n")
    prices = ps.latest_prices_from_csvs({"X": str(csvp)})
    assert prices["X"] == 20.0  # last close
