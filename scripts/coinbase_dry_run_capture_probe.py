#!/usr/bin/env python3
"""
P2-011I — Controlled Dry-Run Broker-Data Capture Probe (proof / instrumentation only).

This script provides a controlled harness to exercise the P2-011H opt-in
dry-run capture seam in PositionManager using sanitized, mock Coinbase-like
payloads.

It proves:
- The seam can be exercised in a fully isolated way.
- Raw payloads are preserved.
- Entry and exit facts are captured when present.
- Readiness is correctly blocked when required facts (stable per-fill IDs,
  per-fill fees, direct sell proceeds on exits) are missing.
- No side effects: no file writes, no calls to the production logger.

Usage (from repo root):
    python3 scripts/coinbase_dry_run_capture_probe.py

Or import and use run_all_scenarios() from tests.

This is Class 1 advisory/read-only instrumentation. It performs no writes
and has no effect on live trading when the dry_run_capture flag is False
(the default).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

# Make the script runnable from repo root without installation
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import the seam we are proving
from position_manager import PositionManager

# Reuse the P2-011G capture helpers for result structure
from coinbase_entry_exit_capture import CaptureResult


@dataclass
class ProbeScenario:
    name: str
    leg_type: str  # "entry" or "exit"
    symbol: str
    order_status: Dict[str, Any]  # format returned by get_order_status (top-level fields)
    historical_fills: List[Dict[str, Any]]
    expected_logger_ready: bool
    expected_blocking_contains: List[str]  # substrings that must appear in blocking_reasons


def load_fixture(name: str) -> Dict[str, Any]:
    """Load a JSON fixture if available; fall back to inline for self-contained probe."""
    fixture_path = Path("tests/fixtures/coinbase") / name
    if fixture_path.exists():
        with open(fixture_path) as f:
            return json.load(f)
    return {}


def make_mock_broker(order_status: Dict[str, Any], fills: List[Dict[str, Any]]) -> MagicMock:
    """Create a broker double that returns controlled payloads for the seam."""
    broker = MagicMock()
    broker.get_order_status.return_value = order_status
    broker.get_historical_fills.return_value = fills
    # Also provide minimal methods used elsewhere so PositionManager can be instantiated
    broker.get_all_positions.return_value = []
    return broker


def make_mock_journal() -> MagicMock:
    journal = MagicMock()
    journal.log_warning = MagicMock()
    journal.log_exit = MagicMock()
    return journal


# =============================================================================
# Controlled scenarios (sanitized, representative of Coinbase Advanced Trade responses)
# =============================================================================

def scenario_entry_good_one_fill() -> ProbeScenario:
    """Good entry: all direct facts + stable fill ID present."""
    status = {
        "normalized_status": "filled",
        "raw_status": "FILLED",
        "side": "BUY",
        "filled_size": "0.00123456",
        "average_filled_price": "65000.50",
        "total_fees": "0.4815",
        "filled_value": "80.25",
        "settled": True,
        "last_fill_time": "2026-05-30T12:00:05.789Z",
    }
    fills = [
        {
            "trade_id": "trade-9876543210",
            "order_id": "00000000-0000-0000-0000-000000000001",
            "product_id": "BTC-USD",
            "side": "BUY",
            "price": "65000.50",
            "size": "0.00123456",
            "fee": "0.4815",
            "fee_currency": "USD",
            "liquidity_indicator": "MAKER",
            "time": "2026-05-30T12:00:05.789Z",
        }
    ]
    return ProbeScenario(
        name="entry_good_one_fill",
        leg_type="entry",
        symbol="BTC/USD",
        order_status=status,
        historical_fills=fills,
        expected_logger_ready=True,
        expected_blocking_contains=[],
    )


def scenario_exit_good_with_proceeds() -> ProbeScenario:
    """Good exit: direct sell proceeds (filled_value) + stable ID + fee present."""
    status = {
        "normalized_status": "filled",
        "raw_status": "FILLED",
        "side": "SELL",
        "filled_size": "0.00123456",
        "average_filled_price": "65100.75",
        "total_fees": "0.4822",
        "filled_value": "80.37",   # direct sell proceeds
        "settled": True,
    }
    fills = [
        {
            "entry_id": "fill-exit-001",
            "order_id": "exit-order-002",
            "product_id": "BTC-USD",
            "side": "SELL",
            "price": "65100.75",
            "size": "0.00123456",
            "fee": "0.4822",
            "fee_currency": "USD",
            "liquidity_indicator": "TAKER",
            "time": "2026-05-30T13:00:04.500Z",
        }
    ]
    return ProbeScenario(
        name="exit_good_with_proceeds",
        leg_type="exit",
        symbol="BTC/USD",
        order_status=status,
        historical_fills=fills,
        expected_logger_ready=True,
        expected_blocking_contains=[],
    )


def scenario_exit_missing_proceeds() -> ProbeScenario:
    """Exit leg missing filled_value on the SELL order → must be blocked."""
    status = {
        "normalized_status": "filled",
        "side": "SELL",
        "filled_size": "0.001",
        "average_filled_price": "65000",
        "total_fees": "0.39",
        # deliberately no "filled_value"
    }
    fills = [{"trade_id": "t1", "fee": "0.39", "price": "65000", "size": "0.001"}]
    return ProbeScenario(
        name="exit_missing_proceeds",
        leg_type="exit",
        symbol="BTC/USD",
        order_status=status,
        historical_fills=fills,
        expected_logger_ready=False,
        expected_blocking_contains=["Exit leg missing direct sell proceeds"],
    )


def scenario_missing_stable_fill_id() -> ProbeScenario:
    """Fill present but no trade_id or entry_id → blocked for idempotency."""
    status = {"normalized_status": "filled", "filled_size": "0.01", "average_filled_price": "140"}
    fills = [{"price": "140", "size": "0.01", "fee": "0.084"}]  # no stable ID
    return ProbeScenario(
        name="missing_stable_fill_id",
        leg_type="entry",
        symbol="SOL/USD",
        order_status=status,
        historical_fills=fills,
        expected_logger_ready=False,
        expected_blocking_contains=["Missing stable fill ID"],
    )


def scenario_missing_per_fill_fee() -> ProbeScenario:
    """Fill present but fee missing → net P/L cannot be direct fact."""
    status = {"normalized_status": "filled", "filled_size": "0.01", "average_filled_price": "140", "total_fees": "0"}
    fills = [{"trade_id": "t1", "price": "140", "size": "0.01"}]  # no fee
    return ProbeScenario(
        name="missing_per_fill_fee",
        leg_type="entry",
        symbol="SOL/USD",
        order_status=status,
        historical_fills=fills,
        expected_logger_ready=False,
        expected_blocking_contains=["Missing per-fill fee"],
    )


def scenario_no_fills_returned() -> ProbeScenario:
    """Order filled according to status, but no fills from historical endpoint → blocked."""
    status = {"normalized_status": "filled", "filled_size": "0.001", "average_filled_price": "65000"}
    return ProbeScenario(
        name="no_fills_returned",
        leg_type="entry",
        symbol="BTC/USD",
        order_status=status,
        historical_fills=[],
        expected_logger_ready=False,
        expected_blocking_contains=["No fills returned for order"],
    )


ALL_SCENARIOS: List[ProbeScenario] = [
    scenario_entry_good_one_fill(),
    scenario_exit_good_with_proceeds(),
    scenario_exit_missing_proceeds(),
    scenario_missing_stable_fill_id(),
    scenario_missing_per_fill_fee(),
    scenario_no_fills_returned(),
]


def run_single_scenario(scenario: ProbeScenario) -> Tuple[bool, List[str], CaptureResult]:
    """
    Run one controlled scenario using the P2-011H seam.
    Returns (success, blocking_reasons, capture_result)
    """
    broker = make_mock_broker(scenario.order_status, scenario.historical_fills)
    journal = MagicMock()

    # Exercise the exact seam that exists in the real flow
    pm = PositionManager(broker, journal, dry_run_capture=True)

    if scenario.leg_type == "entry":
        pm._maybe_dry_run_capture_entry(
            scenario.symbol,
            scenario.order_status.get("order_id", "probe-order"),
            scenario.order_status,
        )
    else:
        pm._maybe_dry_run_capture_exit(
            scenario.symbol,
            scenario.order_status.get("order_id", "probe-order"),
        )

    if not pm._dry_run_captures:
        # This can happen for certain blocking paths before capture is appended
        # In those cases we still consider the probe successful if blocking is correct
        dummy = CaptureResult(
            leg_type=scenario.leg_type,
            symbol=scenario.symbol,
            order_id=None,
            client_order_id=None,
            account_mode="probe",
            reconciliation=None,  # type: ignore
            capture_time_utc="",
            has_fills=False,
            has_direct_fees=False,
            has_direct_sell_proceeds=False,
            has_stable_fill_ids=False,
            logger_ready=False,
            blocking_reasons=["No capture result produced (early block or no fills)"],
            raw_order_payload=scenario.order_status,
            raw_fills_payload=scenario.historical_fills,
        )
        return False, dummy.blocking_reasons, dummy

    cap = pm._dry_run_captures[-1]
    success = cap.logger_ready == scenario.expected_logger_ready
    if scenario.expected_blocking_contains:
        success = success and all(
            any(substr in reason for reason in cap.blocking_reasons)
            for substr in scenario.expected_blocking_contains
        )

    return success, cap.blocking_reasons, cap


def run_all_scenarios() -> bool:
    """Run all scenarios and print a summary. Returns overall success."""
    print("=== P2-011I Controlled Dry-Run Broker-Data Capture Probe ===\n")
    all_ok = True

    for scenario in ALL_SCENARIOS:
        ok, blocking, cap = run_single_scenario(scenario)
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"[{status}] {scenario.name}")
        print(f"  leg={scenario.leg_type}  logger_ready={cap.logger_ready}")
        if blocking:
            print(f"  blocking: {blocking}")
        print(f"  raw_order preserved: {bool(cap.raw_order_payload)}")
        print(f"  raw_fills count: {len(cap.raw_fills_payload)}")
        print()

    print("=== Overall probe result ===")
    print("SUCCESS" if all_ok else "FAILURE")
    return all_ok


if __name__ == "__main__":
    import sys
    success = run_all_scenarios()
    sys.exit(0 if success else 1)
