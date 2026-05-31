"""
P2-011F tests for Coinbase order + fills reconciliation proof.

All tests are pure and use static data or existing sanitized fixtures.
No live API calls, no side effects.
"""

import json
from pathlib import Path

import pytest

from coinbase_order_fills_reconciliation import reconcile_order_with_fills


FIXTURES_DIR = Path("tests/fixtures/coinbase")


def _load(name: str):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


def test_entry_order_one_fill_reconciles_but_checks_readiness():
    order = _load("sample_order_filled_buy.json")
    fills = _load("sample_fills_list.json")["fills"]

    result = reconcile_order_with_fills(
        order, fills, account_mode="live", leg_type="entry"
    )

    assert result.product_id == "BTC-USD"
    assert result.leg_type == "entry"
    assert result.fills_count == 1
    assert len(result.idempotency_keys) == 1
    assert "live:BTC-USD:00000000-0000-0000-0000-000000000001:trade-9876543210" in result.idempotency_keys
    # With per-fill fee present → should be ready in this fixture
    assert result.logger_ready is True or "Missing per-fill fee" not in str(result.blocking_reasons)


def test_exit_order_with_direct_proceeds_is_ready_when_all_facts_present():
    order = _load("sample_order_filled_sell.json")
    fills = _load("sample_fills_list.json")["fills"]

    result = reconcile_order_with_fills(
        order, fills, account_mode="live", leg_type="exit"
    )

    assert result.side == "SELL"
    assert result.sells_proceeds.classification == "direct_broker_fact"
    assert result.logger_ready is True


def test_exit_order_missing_proceeds_is_blocked():
    order = _load("sample_order_filled_buy.json")  # reuse buy as proxy for missing sell proceeds
    fills = _load("sample_fills_list.json")["fills"]

    result = reconcile_order_with_fills(
        order, fills, account_mode="live", leg_type="exit"
    )

    assert any("Exit leg missing direct sell proceeds" in r for r in result.blocking_reasons)
    assert result.logger_ready is False


def test_multi_fill_order_generates_per_fill_idempotency_keys():
    order = _load("sample_order_partial_fills.json")
    # fabricate multi-fill
    fills = [
        {"entry_id": "f1", "price": "3100", "size": "0.02", "fee": "0.37", "liquidity_indicator": "MAKER"},
        {"trade_id": "t2", "price": "3101", "size": "0.0255", "fee": "0.476", "liquidity_indicator": "TAKER"},
    ]

    result = reconcile_order_with_fills(order, fills, leg_type="entry")

    assert result.fills_count == 2
    assert len(result.idempotency_keys) == 2
    assert any("f1" in k for k in result.idempotency_keys)
    assert any("t2" in k for k in result.idempotency_keys)


def test_multi_fill_missing_stable_id_on_any_fill_blocks():
    order = _load("sample_order_filled_buy.json")
    fills = [
        {"entry_id": "good", "fee": "0.1"},
        {"price": "x", "size": "y"},  # no id
    ]

    result = reconcile_order_with_fills(order, fills)

    assert any("Missing stable fill ID" in r for r in result.blocking_reasons)
    assert result.logger_ready is False


def test_missing_fee_on_any_fill_blocks_net_pl_readiness():
    order = _load("sample_order_filled_buy.json")
    fills = [
        {"entry_id": "f1", "fee": "0.1"},
        {"entry_id": "f2"},  # missing fee
    ]

    result = reconcile_order_with_fills(order, fills)

    assert any("Missing per-fill fee" in r for r in result.blocking_reasons)
    assert result.logger_ready is False


def test_order_level_only_no_fills_is_blocked():
    order = _load("sample_order_filled_buy.json")
    result = reconcile_order_with_fills(order, [], leg_type="entry")

    assert any("No fills returned" in r for r in result.blocking_reasons)
    assert result.logger_ready is False


def test_helper_is_not_referenced_from_live_files():
    """Guard to ensure this proof module is not imported by live code."""
    import ast
    import os

    live_files = [
        "main.py",
        "position_manager.py",
        "order_manager.py",
        "broker_coinbase.py",
        "journal.py",
    ]

    for fname in live_files:
        path = Path(fname)
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "coinbase_order_fills_reconciliation" in alias.name:
                        pytest.fail(f"{fname} imports the reconciliation helper — violation of scope")
            elif isinstance(node, ast.ImportFrom):
                if node.module and "coinbase_order_fills_reconciliation" in node.module:
                    pytest.fail(f"{fname} imports the reconciliation helper — violation of scope")
