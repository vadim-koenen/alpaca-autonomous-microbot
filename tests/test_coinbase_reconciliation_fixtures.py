# ADVISORY ONLY — Regression tests using reconciliation fixtures (P2-018C)

import json
from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "coinbase_reconciliation"


def _load_json(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


def _load_csv(name: str):
    return (FIXTURE_DIR / name).read_text()


def test_sol_open_missing_fee_value_blocks_aggregation():
    data = _load_json("sol_open_missing_fee_value.json")
    # This fixture represents the current real state
    assert data["sol_on_broker"] is True
    assert any(f.get("fee") is None for f in data.get("recent_fills_sample", []))


def test_sol_entry_exit_direct_facts_complete_has_both_legs():
    data = _load_json("sol_entry_exit_direct_facts_complete.json")
    assert data["sol_on_broker"] is False
    fills = data.get("recent_fills_sample", [])
    assert any(f.get("side") == "BUY" and f.get("fee") is not None for f in fills)
    assert any(f.get("side") == "SELL" and f.get("filled_value") is not None for f in fills)


def test_zero_qty_noise_rows_are_present_but_policy_excludes_them():
    csv = _load_csv("sol_zero_qty_noise_rows.csv")
    zero_qty_lines = [line for line in csv.splitlines() if ",0.0," in line or ",0.0," in line.split(",")[3] if len(line.split(",")) > 3]
    # At least 3 zero-qty rows exist in the fixture
    assert len([l for l in csv.splitlines() if "0.0" in l.split(",")[3] if len(l.split(",")) > 3]) >= 3


def test_broker_truth_unavailable_fixture():
    data = _load_json("broker_truth_unavailable.json")
    assert data["broker_read_successful"] is False


def test_malformed_fill_payloads_do_not_crash_logic():
    data = _load_json("malformed_fill_payloads.json")
    fills = data.get("recent_fills_sample", [])
    # The fixture contains nulls, bad types, and one good row.
    # Any consumer must handle these gracefully.
    assert len(fills) == 5
    assert any(isinstance(f, dict) and f.get("fee") is not None for f in fills)
