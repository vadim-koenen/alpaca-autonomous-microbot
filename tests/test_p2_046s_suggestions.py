"""P2-046S — proactive suggestion engine tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import suggestion_engine as se


def base_state(**over):
    s = {"mode": "paper", "total_value": 500.0, "contribution": 10.0, "cadence_days": 7,
         "days_since_contribution": 2, "reinvest_amount": 0.0, "max_drift": 0.0,
         "rebalance_band": 0.25, "risk_alerts": 0, "tier": None, "funded": None}
    s.update(over)
    return s


def test_on_track_when_nothing_to_do():
    top = se.top_suggestion(base_state())
    assert top["type"] == "on_track"


def test_idle_account_suggests_first_contribution():
    top = se.top_suggestion(base_state(days_since_contribution=None))
    assert top["type"] == "contribute" and "idle" in top["message"].lower()


def test_overdue_contribution():
    top = se.top_suggestion(base_state(days_since_contribution=9))
    assert top["type"] == "contribute" and "9 days" in top["message"]


def test_risk_alert_takes_top_priority():
    # even with other conditions, a risk alert wins
    top = se.top_suggestion(base_state(risk_alerts=2, days_since_contribution=30, reinvest_amount=5))
    assert top["type"] == "risk"


def test_reinvest_suggestion():
    top = se.top_suggestion(base_state(days_since_contribution=1, reinvest_amount=3.50))
    assert top["type"] == "reinvest" and "3.50" in top["message"]


def test_underfunded_live():
    top = se.top_suggestion(base_state(mode="live", funded=False, days_since_contribution=1))
    assert top["type"] == "fund"


def test_rebalance_when_drifted():
    top = se.top_suggestion(base_state(days_since_contribution=1, max_drift=0.40))
    assert top["type"] == "rebalance"


def test_tier_progress_when_close():
    tier = {"upgrade_at": 1000.0, "next_label": "Build"}
    top = se.top_suggestion(base_state(total_value=850.0, days_since_contribution=1, tier=tier))
    assert top["type"] == "tier" and "Build" in top["message"]


def test_priority_ordering_is_stable():
    items = se.suggest(base_state(risk_alerts=1, reinvest_amount=2, days_since_contribution=9, max_drift=0.4))
    prios = [s["priority"] for s in items]
    assert prios == sorted(prios) and items[0]["type"] == "risk"
