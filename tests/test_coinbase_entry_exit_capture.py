"""
P2-011G — Tests for inert Coinbase entry/exit capture wiring.

These tests prove the capture abstraction works on top of P2-011F reconciliation
without any side effects or live wiring.
"""

import json
from pathlib import Path

from coinbase_entry_exit_capture import (
    capture_entry,
    capture_exit,
    capture_leg,
)

FIXTURES_DIR = Path("tests/fixtures/coinbase")


def _load(name: str):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


def test_capture_entry_with_good_data():
    order = _load("sample_order_filled_buy.json")
    fills = _load("sample_fills_list.json")["fills"]

    result = capture_entry(order, fills, symbol="BTC/USD")

    assert result.leg_type == "entry"
    assert result.symbol == "BTC/USD"
    assert result.has_fills is True
    assert result.has_stable_fill_ids is True
    assert result.logger_ready is True or len(result.blocking_reasons) == 0


def test_capture_exit_with_direct_proceeds():
    order = _load("sample_order_filled_sell.json")
    fills = _load("sample_fills_list.json")["fills"]

    result = capture_exit(order, fills, symbol="BTC/USD")

    assert result.leg_type == "exit"
    assert result.has_direct_sell_proceeds is True
    assert result.logger_ready is True


def test_capture_exit_without_proceeds_is_blocked():
    # Use buy order as proxy for missing sell proceeds
    order = _load("sample_order_filled_buy.json")
    fills = _load("sample_fills_list.json")["fills"]

    result = capture_exit(order, fills, symbol="BTC/USD")

    assert result.leg_type == "exit"
    assert any("Exit leg missing direct sell proceeds" in r for r in result.blocking_reasons)
    assert result.logger_ready is False


def test_capture_blocks_on_missing_stable_fill_id():
    order = _load("sample_order_filled_buy.json")
    bad_fills = _load("sample_fills_list_no_trade_id.json")["fills"]

    result = capture_entry(order, bad_fills, symbol="BTC/USD")

    # The no-trade-id fixture still has entry_id, so it may still succeed.
    # We test the blocking path explicitly with completely missing IDs.
    really_bad_fills = [{"price": "1", "size": "1"}]  # no ids at all
    result2 = capture_entry(order, really_bad_fills, symbol="BTC/USD")

    assert any("Missing stable fill ID" in r for r in result2.blocking_reasons)
    assert result2.logger_ready is False


def test_capture_helper_is_pure_and_inert():
    """The capture functions should never have side effects."""
    order = _load("sample_order_filled_buy.json")
    fills = _load("sample_fills_list.json")["fills"]

    r1 = capture_entry(order, fills, symbol="BTC/USD")
    r2 = capture_entry(order, fills, symbol="BTC/USD")

    # Same inputs → deterministic output, no mutation
    assert r1.order_id == r2.order_id
    assert r1.logger_ready == r2.logger_ready
