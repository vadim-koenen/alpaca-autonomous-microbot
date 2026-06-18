"""P2-046U — honest research assistant tests (pure analytics, no network, no predictions)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research_assistant as ra


def test_annualized_return():
    # double over exactly one trading year -> ~100%
    closes = [100.0] * 1 + [100.0 * (2 ** (i / 252)) for i in range(1, 253)]
    assert abs(ra.annualized_return(closes) - 100.0) < 2.0


def test_max_drawdown():
    assert ra.max_drawdown([100, 120, 60, 90]) == 50.0   # peak 120 -> trough 60
    assert ra.max_drawdown([100, 110, 120]) == 0.0


def test_vol_zero_for_flat():
    assert ra.annualized_vol([100.0] * 50) == 0.0


def test_pearson_perfect_and_anti():
    assert ra.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert ra.pearson([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert ra.pearson([1], [1]) is None


def test_aligned_returns_uses_common_dates():
    a = {"2024-01-01": 100, "2024-01-02": 101, "2024-01-03": 102}
    b = {"2024-01-02": 50, "2024-01-03": 51, "2024-01-04": 52}
    ra_, rb_ = ra.aligned_returns(a, b)
    assert len(ra_) == 1 and len(rb_) == 1  # only 2 common dates -> 1 return each


def test_research_asset_insufficient_history():
    series = {f"2024-01-{i:02d}": 100.0 + i for i in range(1, 10)}  # < 30 days
    out = ra.research_asset("X", "X", series)
    assert out["error"] == "insufficient_history" and out["is_recommendation"] is False


def test_research_asset_full_briefing_never_recommends():
    # 200 days of gentle uptrend
    series = {f"d{i:04d}": 100.0 * (1.0005 ** i) for i in range(200)}
    out = ra.research_asset("SCHD", "Dividend Stocks", series)
    assert out["is_recommendation"] is False
    assert "disclaimer" in out and "NOT a prediction" in out["disclaimer"]
    assert out["annualized_return_pct"] > 0 and out["max_drawdown_pct"] >= 0
    assert "role" in out and "fit" in out
    # the analytical fields must never contain a buy/sell directive (disclaimer may mention it)
    assert "buy" not in out["role"].lower() and "sell" not in out["role"].lower()
    assert "buy" not in out["fit"].lower() and "sell" not in out["fit"].lower()


def test_research_asset_correlation_with_basket():
    asset = {f"d{i:04d}": 100.0 + i for i in range(60)}        # rising
    basket = {f"d{i:04d}": 200.0 + 2 * i for i in range(60)}   # rising in lockstep
    out = ra.research_asset("X", "X", asset, basket)
    assert out["correlation_to_basket"] is not None
    assert out["correlation_to_basket"] > 0.9
    assert "similar" in out["fit"].lower() or "overlap" in out["fit"].lower()


def test_role_bands():
    assert "defensive" in ra._role(2.0)
    assert "core" in ra._role(12.0)
    assert "growth" in ra._role(25.0)
    assert "high-risk" in ra._role(60.0)
