"""
P2-011I — Tests for the controlled dry-run broker-data capture probe.

These tests prove that the probe exercises the P2-011H seam correctly
with no side effects, no logger writes, and correct readiness/blocking behavior.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.coinbase_dry_run_capture_probe import (
    ProbeScenario,
    run_single_scenario,
    scenario_entry_good_one_fill,
    scenario_exit_good_with_proceeds,
    scenario_exit_missing_proceeds,
    scenario_missing_stable_fill_id,
    scenario_missing_per_fill_fee,
    scenario_no_fills_returned,
)


def test_probe_script_runs_all_scenarios():
    """The main harness should execute without error and return a boolean."""
    from scripts.coinbase_dry_run_capture_probe import run_all_scenarios
    result = run_all_scenarios()
    assert isinstance(result, bool)


def test_entry_good_scenario_is_ready():
    scenario = scenario_entry_good_one_fill()
    ok, blocking, cap = run_single_scenario(scenario)
    assert ok is True
    assert cap.logger_ready is True
    assert len(blocking) == 0
    assert cap.raw_order_payload  # raw preserved
    assert len(cap.raw_fills_payload) == 1


def test_exit_with_proceeds_is_ready():
    scenario = scenario_exit_good_with_proceeds()
    ok, blocking, cap = run_single_scenario(scenario)
    assert ok is True
    assert cap.has_direct_sell_proceeds is True
    assert cap.logger_ready is True


def test_exit_missing_proceeds_is_blocked():
    scenario = scenario_exit_missing_proceeds()
    ok, blocking, cap = run_single_scenario(scenario)
    assert ok is True, "observed behavior should match the scenario's declared expectation (blocked)"
    assert cap.logger_ready is False
    assert any("Exit leg missing direct sell proceeds" in r for r in blocking)


def test_missing_stable_fill_id_blocks():
    scenario = scenario_missing_stable_fill_id()
    ok, blocking, _ = run_single_scenario(scenario)
    assert ok is True, "observed behavior should match the scenario's declared expectation (blocked)"
    assert any("Missing stable fill ID" in r for r in blocking)


def test_missing_per_fill_fee_blocks_net_pl():
    scenario = scenario_missing_per_fill_fee()
    ok, blocking, _ = run_single_scenario(scenario)
    assert ok is True, "observed behavior should match the scenario's declared expectation (blocked)"
    assert any("Missing per-fill fee" in r for r in blocking)


def test_no_fills_returned_blocks():
    scenario = scenario_no_fills_returned()
    ok, blocking, _ = run_single_scenario(scenario)
    assert ok is True, "observed behavior should match the scenario's declared expectation (blocked)"
    assert any("No fills returned for order" in r for r in blocking)


def test_probe_performs_no_logger_writes_or_file_io(tmp_path, monkeypatch):
    """Critical safety: the probe must never touch the production logger or CSV."""
    from scripts import coinbase_dry_run_capture_probe as probe_mod

    # Redirect the CSV path
    monkeypatch.setattr(
        probe_mod,
        "DEFAULT_COINBASE_FILLS_CSV",
        tmp_path / "must_not_be_written.csv",
        raising=False,
    )

    scenario = scenario_entry_good_one_fill()

    with patch("coinbase_fill_logger.append_coinbase_fill_row") as mock_append:
        ok, _, cap = run_single_scenario(scenario)

        mock_append.assert_not_called()
        # The redirected CSV should not have been created by the probe
        assert not (tmp_path / "must_not_be_written.csv").exists()
        assert ok is True  # good scenario still works


def test_all_blocking_scenarios_are_correctly_detected():
    """Meta-test: every scenario that should be blocked actually is (i.e. observed matches declared expectation)."""
    blocked_scenarios = [
        scenario_exit_missing_proceeds(),
        scenario_missing_stable_fill_id(),
        scenario_missing_per_fill_fee(),
        scenario_no_fills_returned(),
    ]
    for s in blocked_scenarios:
        ok, blocking, cap = run_single_scenario(s)
        assert ok is True, f"{s.name} observed behavior should match its declared blocking expectation"
        assert cap.logger_ready is False
        assert len(blocking) > 0
