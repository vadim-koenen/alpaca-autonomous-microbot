"""
tests/test_p2_044a_pivot_feasibility_matrix.py — P2-044A unit tests.

Pure stdlib + pytest. No broker, no network, no pyarrow/duckdb. Deterministic.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import pivot_feasibility_matrix as pfm


# ---------------------------------------------------------------- cost / move math

def test_round_trip_cost_is_both_sides():
    a = pfm.LaneAssumptions(
        key="x", label="x", venue="v", instrument="i",
        horizon_label="h", horizon_minutes=90.0,
        fee_bps_per_side=120.0, spread_bps_per_side=3.0, slippage_bps_per_side=5.0,
        expected_move_bps_override=None, min_trade_notional_usd=1.0,
        market_hours_only=False, pdt_constrained=False, prior_p_durable_edge=0.0,
        assumptions_source="t",
    )
    # 2 * (120 + 3 + 5) = 256
    assert pfm.round_trip_cost_bps(a) == pytest.approx(256.0)


def test_expected_move_sqrt_time_scaling():
    # 4x the anchor horizon => 2x the move (sqrt(4)=2)
    a = pfm.LaneAssumptions(
        key="x", label="x", venue="v", instrument="i",
        horizon_label="h", horizon_minutes=pfm.ANCHOR_HORIZON_MIN * 4.0,
        fee_bps_per_side=0.0, spread_bps_per_side=0.0, slippage_bps_per_side=0.0,
        expected_move_bps_override=None, min_trade_notional_usd=1.0,
        market_hours_only=False, pdt_constrained=False, prior_p_durable_edge=0.0,
        assumptions_source="t",
    )
    assert pfm.expected_move_bps(a) == pytest.approx(pfm.ANCHOR_MOVE_BPS * 2.0)


def test_expected_move_override_used():
    a = pfm.default_lanes()[0]
    a_override = pfm.LaneAssumptions(**{**a.__dict__, "expected_move_bps_override": 150.0})
    assert pfm.expected_move_bps(a_override) == pytest.approx(150.0)


def test_breakeven_win_rate_formula():
    # cost == move => p* = 0.5 + 1/2 = 1.0 (impossible)
    assert pfm.breakeven_win_rate(100.0, 100.0) == pytest.approx(1.0)
    # cost == 0 => fair coin breakeven 0.5
    assert pfm.breakeven_win_rate(100.0, 0.0) == pytest.approx(0.5)
    # cost = move/2 => p* = 0.75
    assert pfm.breakeven_win_rate(100.0, 50.0) == pytest.approx(0.75)


def test_breakeven_clamped_when_cost_exceeds_move():
    assert pfm.breakeven_win_rate(50.0, 500.0) == 1.0
    assert pfm.breakeven_win_rate(0.0, 100.0) == 1.0


# ---------------------------------------------------------------- capital / compliance

def test_live_capital_compliance_blocks_oversized_min_notional():
    a = pfm.LaneAssumptions(
        key="big", label="big", venue="v", instrument="i",
        horizon_label="h", horizon_minutes=90.0,
        fee_bps_per_side=0.0, spread_bps_per_side=0.0, slippage_bps_per_side=0.0,
        expected_move_bps_override=100.0,
        min_trade_notional_usd=5.0,  # > $3 live cap
        market_hours_only=False, pdt_constrained=False, prior_p_durable_edge=0.2,
        assumptions_source="t",
    )
    assert pfm.live_capital_compliant(a) is False
    r = pfm.evaluate_lane(a)
    assert any("min_notional" in c for c in r.constraints)


# ---------------------------------------------------------------- verdict logic

def test_falsified_coinbase_taker_short_is_infeasible():
    lanes = {a.key: a for a in pfm.default_lanes()}
    r = pfm.evaluate_lane(lanes["coinbase_taker_short"])
    # 90-min move (~80bps) far below taker round-trip cost => unwinnable
    assert r.hurdle_ratio < pfm.HURDLE_INFEASIBLE_BELOW
    assert r.verdict == "INFEASIBLE"
    assert r.composite_score == 0.0


def test_coinbase_maker_short_not_feasible_to_test():
    lanes = {a.key: a for a in pfm.default_lanes()}
    r = pfm.evaluate_lane(lanes["coinbase_maker_short"])
    # maker halves fees but 90-min move still doesn't clear a >=2x hurdle
    assert r.verdict in ("INFEASIBLE", "MARGINAL")


def test_no_trade_baseline_present_and_scored_zero():
    lanes = {a.key: a for a in pfm.default_lanes()}
    r = pfm.evaluate_lane(lanes["no_trade_park"])
    assert r.verdict == "BASELINE"
    assert r.composite_score == 0.0


def test_equities_intraday_flagged_pdt_constrained():
    lanes = {a.key: a for a in pfm.default_lanes()}
    r = pfm.evaluate_lane(lanes["alpaca_equities_etf_intraday"])
    assert any("pdt_constrained" in c for c in r.constraints)


def test_low_cost_high_hurdle_lane_is_feasible_to_test():
    # commission-free swing ETF: cost ~6bps, move 150bps => hurdle ~25x
    lanes = {a.key: a for a in pfm.default_lanes()}
    r = pfm.evaluate_lane(lanes["alpaca_equities_etf_swing"])
    assert r.hurdle_ratio >= pfm.HURDLE_FEASIBLE_AT_OR_ABOVE
    assert r.verdict == "FEASIBLE_TO_TEST"


# ---------------------------------------------------------------- matrix / recommendation

def test_recommended_lane_is_not_a_coinbase_short_horizon_lane():
    m = pfm.build_matrix()
    assert m["recommended_lane_key"] not in ("coinbase_taker_short", "coinbase_maker_short")


def test_recommended_lane_is_a_real_testable_lane():
    m = pfm.build_matrix()
    rec = m["recommended_lane_key"]
    by_key = {l["key"]: l for l in m["lanes"]}
    assert by_key[rec]["verdict"] in ("FEASIBLE_TO_TEST", "MARGINAL")


def test_matrix_has_disclaimer_and_all_lanes():
    m = pfm.build_matrix()
    assert "FEASIBILITY SCREEN ONLY" in m["disclaimer"]
    assert len(m["lanes"]) == len(pfm.default_lanes())


def test_determinism_same_inputs_same_lanes_payload():
    m1 = pfm.build_matrix()
    m2 = pfm.build_matrix()
    # generated_utc differs; lane payload + recommendation must be identical
    assert m1["lanes"] == m2["lanes"]
    assert m1["recommended_lane_key"] == m2["recommended_lane_key"]


# ---------------------------------------------------------------- output side effects

def test_write_outputs_creates_files(tmp_path: Path):
    m = pfm.build_matrix()
    paths = pfm.write_outputs(m, tmp_path)
    jp, mp = Path(paths["json"]), Path(paths["md"])
    assert jp.exists() and mp.exists()
    loaded = json.loads(jp.read_text())
    assert loaded["schema"] == "p2_044a_pivot_feasibility_matrix/v1"
    assert "Pivot Feasibility Matrix" in mp.read_text()


def test_main_writes_to_custom_dir(tmp_path: Path):
    rc = pfm.main(["--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "p2_044a_pivot_feasibility_matrix.json").exists()
