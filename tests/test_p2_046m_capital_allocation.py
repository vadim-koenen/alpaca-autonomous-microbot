"""P2-046M — capital-adaptive allocation (glide path) tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
import capital_allocation as cap
import planner_service as ps
from allocator_engine import Portfolio

PRICES = {"SGOV": 100.0, "SPY": 500.0, "BND": 70.0, "GLD": 300.0, "BTC": 60000.0}


def test_tiers_valid():
    cap.validate_tiers()  # raises if misconfigured


def test_tier_for_capital_bands():
    assert cap.tier_for_capital(0)["label"] == "Seed"
    assert cap.tier_for_capital(999)["label"] == "Seed"
    assert cap.tier_for_capital(1000)["label"] == "Build"
    assert cap.tier_for_capital(4999)["label"] == "Build"
    assert cap.tier_for_capital(5000)["label"] == "Grow"
    assert cap.tier_for_capital(1_000_000)["label"] == "Grow"


def test_weights_sum_to_one_each_tier():
    for v in (0, 2000, 50000):
        w = cap.weights_for_capital(v)
        assert abs(sum(w.values()) - 1.0) < 1e-9


def test_seed_is_safest_grow_is_most_equity():
    seed = cap.weights_for_capital(0)
    grow = cap.weights_for_capital(50000)
    assert seed["SGOV"] > grow["SGOV"]       # more T-bills when small
    assert grow["SPY"] > seed["SPY"]         # more equity when large
    assert "BTC" not in seed                 # no crypto in the seed tier
    assert grow.get("BTC", 0) > 0


def test_tier_info_reports_upgrade():
    info = cap.tier_for_capital and cap.__dict__  # noqa - keep import used
    ti = cap.tier_info(500)
    assert ti["label"] == "Seed" and ti["upgrade_at"] == 1000.0 and ti["next_label"] == "Build"
    top = cap.tier_info(99999)
    assert top["label"] == "Grow" and top["upgrade_at"] is None


# --- adaptive build_plan ------------------------------------------------------

def _adaptive_cfg():
    c = app_config.default_config()
    c.adaptive_allocation = True
    return c


def test_build_plan_seed_tier_when_empty():
    plan = ps.build_plan(Portfolio(), PRICES, _adaptive_cfg(), contribution=100.0)
    assert plan["adaptive"] is True and plan["tier"]["label"] == "Seed"
    assert set(plan["target_weights"]) == {"SGOV", "SPY", "GLD"}
    assert abs(plan["target_weights"]["SGOV"] - 0.70) < 1e-6


def test_build_plan_build_tier_midsize():
    pf = Portfolio(holdings={"SGOV": 20.0})  # $2,000 -> Build tier
    plan = ps.build_plan(pf, PRICES, _adaptive_cfg(), contribution=100.0)
    assert plan["tier"]["label"] == "Build"
    assert "BTC" in plan["target_weights"] and "BND" in plan["target_weights"]


def test_build_plan_grow_tier_large():
    pf = Portfolio(holdings={"SGOV": 100.0})  # $10,000 -> Grow tier
    plan = ps.build_plan(pf, PRICES, _adaptive_cfg(), contribution=100.0)
    assert plan["tier"]["label"] == "Grow"
    assert abs(plan["target_weights"]["SPY"] - 0.30) < 1e-6


def test_non_adaptive_uses_config_weights():
    c = app_config.default_config()  # adaptive off
    plan = ps.build_plan(Portfolio(), {"SPY": 500, "GLD": 300, "SLV": 25, "QQQ": 400, "BTC": 60000},
                         c, contribution=100.0)
    assert plan["adaptive"] is False and plan["tier"] is None
