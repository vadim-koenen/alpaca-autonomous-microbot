"""P2-046N — get_dashboard (stupid-simple instant read) tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
import portfolio_store as store
from allocator_engine import Portfolio
from app_api import AccumulatorAPI

PRICES = {"SPY": 50.0, "GLD": 20.0, "SLV": 10.0, "QQQ": 40.0, "BTC": 1000.0}


class FakeBrokerPL:
    def __init__(self, positions):
        self.positions = positions  # {sym: {market_value,total_pl,today_pl,plpc}}

    def submit_orders(self, orders):
        return []

    def account_snapshot(self):
        holdings = {s: 1.0 for s in self.positions}
        return {"cash": 100000.0, "equity": 100000.0, "holdings": holdings,
                "positions": self.positions}


def test_dashboard_simulate_empty(tmp_path):
    api = AccumulatorAPI(config=app_config.default_config(), state_path=tmp_path / "s.json",
                         history_path=tmp_path / "h.jsonl", price_provider=lambda: dict(PRICES))
    d = api.get_dashboard()
    assert d["mode"] == "simulate" and d["total_value"] == 0.0
    assert d["holdings"] == [] and d["direction"] == "flat"
    assert d["leader"] is None and d["laggard"] is None


def test_dashboard_simulate_with_holdings(tmp_path):
    api = AccumulatorAPI(config=app_config.default_config(), state_path=tmp_path / "s.json",
                         history_path=tmp_path / "h.jsonl", price_provider=lambda: dict(PRICES))
    store.save_portfolio(Portfolio(holdings={"SPY": 1.0, "BTC": 0.01}), tmp_path / "s.json")
    d = api.get_dashboard()
    assert d["total_value"] == 50.0 + 10.0
    names = {h["name"] for h in d["holdings"]}
    assert "US Stocks" in names and "Bitcoin" in names  # plain-English names


def test_dashboard_paper_pl_and_drivers(tmp_path):
    c = app_config.default_config(); c.live_paper = True
    positions = {
        "BTC": {"market_value": 12.0, "total_pl": 2.0, "today_pl": 1.5, "plpc": 0.20},
        "GLD": {"market_value": 25.0, "total_pl": -1.0, "today_pl": -0.5, "plpc": -0.04},
    }
    api = AccumulatorAPI(config=c, state_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl",
                         price_provider=lambda: dict(PRICES),
                         broker_factory=lambda: FakeBrokerPL(positions))
    d = api.get_dashboard()
    assert d["mode"] == "paper"
    assert d["total_value"] == 37.0 and d["total_pl"] == 1.0
    assert d["direction"] == "up"
    assert d["leader"]["name"] == "Bitcoin" and d["leader"]["amount"] == 1.5     # biggest today gain
    assert d["laggard"]["name"] == "Gold" and d["laggard"]["amount"] == -0.5      # biggest today drag
    # holdings sorted by value desc -> Gold ($25) before Bitcoin ($12)
    assert d["holdings"][0]["symbol"] == "GLD"


def test_dashboard_direction_down(tmp_path):
    c = app_config.default_config(); c.live_paper = True
    positions = {"BTC": {"market_value": 8.0, "total_pl": -2.0, "today_pl": -2.0, "plpc": -0.2}}
    api = AccumulatorAPI(config=c, state_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl",
                         price_provider=lambda: dict(PRICES),
                         broker_factory=lambda: FakeBrokerPL(positions))
    d = api.get_dashboard()
    assert d["direction"] == "down" and d["total_pl"] == -2.0
    assert d["laggard"]["name"] == "Bitcoin" and d["leader"] is None
