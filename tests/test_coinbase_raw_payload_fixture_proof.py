"""
P2-011C tests for raw Coinbase payload fixture proof.

All tests are pure, use static fixtures only, and assert on the classification logic.
"""

import json
from pathlib import Path

import pytest

from scripts.coinbase_raw_payload_fixture_proof import (
    analyze_fills_payload,
    analyze_order_payload,
    load_fixture,
    run_full_proof,
)

FIXTURES_DIR = Path("tests/fixtures/coinbase")


def test_fixtures_load():
    order = load_fixture("sample_order_filled_buy.json")
    fills = load_fixture("sample_fills_list.json")
    assert "order" in order
    assert "fills" in fills
    assert float(order["order"]["filled_size"]) > 0


def test_order_level_provides_cumulative_facts():
    order = load_fixture("sample_order_filled_buy.json")
    analysis = analyze_order_payload(order, "test")
    field_names = {f.name for f in analysis.fields}
    assert "filled_size" in field_names
    assert "average_filled_price" in field_names
    assert "total_fees" in field_names
    assert analysis.gross_pnl_reconstructible is True
    assert analysis.net_pnl_reconstructible is True


def test_fills_list_provides_per_fill_and_liquidity():
    fills = load_fixture("sample_fills_list.json")
    analysis = analyze_fills_payload(fills, "test")
    assert analysis.has_per_fill_breakdown is True
    assert analysis.has_liquidity_indicator is True
    assert analysis.has_stable_fill_id is True


def test_full_proof_concludes_hook_blocked():
    results = run_full_proof()
    assessment = results["assessment"]
    # Per hard safety rule in the task
    assert assessment["7_direct_sell_proceeds"] is False
    assert len(assessment["15_blocked_reasons"]) > 0
    assert assessment["13_current_csv_logger_safe"] is False


def test_idempotency_requires_fills_list():
    results = run_full_proof()
    assessment = results["assessment"]
    assert "order_id + (trade_id or entry_id)" in assessment["11_idempotency_candidate"]
    assert assessment["10_stable_idempotency_key_proven"] is True  # only because we have the fills fixture
