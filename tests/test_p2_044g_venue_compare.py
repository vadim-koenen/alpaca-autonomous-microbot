"""
tests/test_p2_044g_venue_compare.py — P2-044G venue comparison tests.
Pure stdlib + pytest. No broker, no network. Deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import venue_compare as vc
import equities_swing_backtest_gate as gate


def _uptrend(n=400, step=0.5, start=100.0):
    bars, price, day = [], start, datetime(2024, 1, 1)
    for _ in range(n):
        o, c = price, price + step
        bars.append(gate.Bar(day.strftime("%Y-%m-%d"), o, c + 0.2, o - 0.2, c, 1e6))
        price = c
        day += timedelta(days=1)
    return bars


def test_all_four_venues_present():
    assert set(vc.VENUES) == {"coinbase_taker", "coinbase_maker", "alpaca_crypto", "alpaca_equities"}


def test_cost_ordering_coinbase_worst_equities_best():
    rt = {k: v["costs"].round_trip_cost_bps for k, v in vc.VENUES.items()}
    assert rt["coinbase_taker"] > rt["coinbase_maker"] > rt["alpaca_crypto"] > rt["alpaca_equities"]


def test_compare_runs_all_venues_on_crypto_only():
    c = vc.compare(_uptrend(400), None, min_trades=5, decision_grade=True)
    venues = {r["venue"] for r in c["results"]}
    assert venues == set(vc.VENUES)
    # equities venue flagged as data_mismatch when no equities csv supplied
    eq = next(r for r in c["results"] if r["venue"] == "alpaca_equities")
    assert eq["data_mismatch"] is True


def test_net_ev_improves_as_fees_fall():
    c = vc.compare(_uptrend(400), None, min_trades=5, decision_grade=True)
    by = {r["venue"]: r["net_ev_per_trade_bps"] for r in c["results"]}
    # same price path, lower fees => higher net EV per trade
    assert by["alpaca_equities"] > by["alpaca_crypto"] > by["coinbase_maker"] > by["coinbase_taker"]


def test_results_sorted_by_net_ev_desc():
    c = vc.compare(_uptrend(400), None, min_trades=5)
    evs = [r["net_ev_per_trade_bps"] for r in c["results"]]
    assert evs == sorted(evs, reverse=True)


def test_separate_equities_csv_clears_data_mismatch():
    c = vc.compare(_uptrend(400), _uptrend(400, step=0.4), min_trades=5)
    eq = next(r for r in c["results"] if r["venue"] == "alpaca_equities")
    assert eq["data_mismatch"] is False


def test_recommendation_present_and_never_authorizes_live():
    c = vc.compare(_uptrend(400), None, min_trades=5)
    assert isinstance(c["recommendation"], str) and c["recommendation"]
    assert c["authorizes_live"] is False


def test_synthetic_main_writes_outputs(tmp_path: Path):
    rc = vc.main(["--out-dir", str(tmp_path)])
    assert rc == 0
    jp = tmp_path / "p2_044g_venue_compare.json"
    assert jp.exists()
    loaded = json.loads(jp.read_text())
    assert loaded["schema"] == "p2_044g_venue_compare/v1"
    assert loaded["authorizes_live"] is False
