"""P2-046T — selectable allocation presets tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
import capital_allocation as cap
import planner_service as ps
from allocator_engine import Portfolio
from app_api import AccumulatorAPI

PRICES = {"SGOV": 100.0, "SCHD": 30.0, "VTI": 300.0, "BND": 70.0, "GLD": 300.0, "BTC": 60000.0}


def test_all_presets_valid_and_sum_to_one():
    for key, p in cap.PRESETS.items():
        for tier in p["tiers"]:
            assert abs(sum(tier["weights"].values()) - 1.0) < 1e-9, key


def test_presets_ordered_by_risk():
    # at the same capital, preservation holds more cash than growth; growth holds more equity
    pres = cap.weights_for_capital(50000, "preservation")
    grow = cap.weights_for_capital(50000, "growth")
    assert pres["SGOV"] > grow["SGOV"]
    assert grow.get("VTI", 0) > pres.get("VTI", 0)


def test_unknown_preset_falls_back_to_default():
    assert cap.weights_for_capital(0, "nonsense") == cap.weights_for_capital(0, cap.DEFAULT_PRESET)


def test_list_presets_shape():
    items = cap.list_presets()
    keys = {i["key"] for i in items}
    assert {"preservation", "income", "growth"} <= keys
    assert all("label" in i and "description" in i for i in items)


def test_build_plan_uses_selected_preset():
    c = app_config.default_config(); c.adaptive_allocation = True; c.preset = "growth"
    plan = ps.build_plan(Portfolio(), PRICES, c, contribution=100.0)
    # growth Seed tier includes VTI; income Seed does not
    assert "VTI" in plan["target_weights"]


def test_api_get_and_set_preset(tmp_path):
    cfgp = tmp_path / "cfg.json"
    api = AccumulatorAPI(config=app_config.default_config(), config_path=None,
                         state_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl",
                         price_provider=lambda: dict(PRICES))
    api._config_path = cfgp  # persist target
    assert api.get_presets()["current"] == "income"
    api.set_preset("growth")
    assert api.config.preset == "growth"
    assert app_config.load_config(cfgp).preset == "growth"  # persisted


def test_api_set_preset_rejects_unknown(tmp_path):
    api = AccumulatorAPI(config=app_config.default_config(),
                         state_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl",
                         price_provider=lambda: dict(PRICES))
    api._config_path = tmp_path / "cfg.json"
    try:
        api.set_preset("bogus")
        assert False
    except ValueError:
        pass
