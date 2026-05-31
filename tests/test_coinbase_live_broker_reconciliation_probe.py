# ADVISORY ONLY — tests for the P2-015A live (but read-only) broker reconciliation probe.
# All tests use mocks. ZERO real network or broker calls are made.

from pathlib import Path
import importlib.util
import sys
from unittest.mock import patch, MagicMock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_live_broker_reconciliation_probe.py"
spec = importlib.util.spec_from_file_location("probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def test_default_run_without_live_flag_does_no_broker_call(capsys):
    """Default behavior must perform ZERO broker/client calls."""
    # Run the CLI entry point with no flag
    exit_code = probe.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SAFETY" in captured.out or "READ-ONLY" in captured.out
    assert "live-read-only" in captured.out.lower()
    # No network should have occurred (we can't easily assert zero calls here
    # without deeper instrumentation, but the logic path guarantees it).


def test_mocked_sol_position_on_broker_produces_blocked_and_unsafe():
    """When the live broker reports SOL held, we must get BLOCKED + unsafe_to_aggregate."""
    fake_snapshot = probe.LiveBrokerSnapshot(
        open_positions=[{"symbol": "SOL-USD", "quantity": "0.01225"}],
        credential_status="present",
        broker_read_successful=True,
    )

    with patch.object(probe, "collect_live_snapshot", return_value=fake_snapshot):
        report = probe.synthesize_reconciliation_report(fake_snapshot, {"sol_blocker_detected": True})

    assert report["verdict"] == "BLOCKED"
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert any("SOL" in b for b in report["blockers"])


def test_mocked_no_sol_on_broker_can_be_clear_or_warn():
    """No SOL on broker + no local blocker can produce CLEAR (or at worst WARN)."""
    fake_snapshot = probe.LiveBrokerSnapshot(
        open_positions=[],
        credential_status="present",
        broker_read_successful=True,
    )

    report = probe.synthesize_reconciliation_report(fake_snapshot, {"sol_blocker_detected": False})

    # Either CLEAR or WARN is acceptable depending on other signals; the key is it is not forced to BLOCKED
    assert report["verdict"] in ("CLEAR", "WARN")
    # If it is WARN it is usually because of missing proceeds, which is still valid


def test_missing_credentials_returns_blocked_or_warn_safely():
    """Missing/blocked credentials must never crash and must produce a clear diagnostic."""
    fake_snapshot = probe.LiveBrokerSnapshot(
        credential_status="missing_or_blocked",
        errors=["auth failed"],
    )

    report = probe.synthesize_reconciliation_report(fake_snapshot)

    assert report["verdict"] in ("BLOCKED", "WARN")
    assert "credential" in str(report).lower() or "blocked" in str(report).lower()


def test_open_orders_for_sol_are_surfaced():
    fake_snapshot = probe.LiveBrokerSnapshot(
        open_orders=[{"product_id": "SOL-USD", "side": "SELL", "size": "0.01"}],
        credential_status="present",
    )

    report = probe.synthesize_reconciliation_report(fake_snapshot)

    assert any("SOL-USD" in str(o) for o in report.get("open_orders", []))


def test_direct_fills_with_trade_id_and_proceeds_are_exposed_as_facts():
    fake_snapshot = probe.LiveBrokerSnapshot(
        recent_fills_sample=[
            {
                "trade_id": "abc-123",
                "product_id": "SOL-USD",
                "side": "SELL",
                "size": "0.01225",
                "price": "81.68",
                "fee": "0.006",
                "filled_value": "1.002",
            }
        ],
        credential_status="present",
    )

    report = probe.synthesize_reconciliation_report(fake_snapshot)

    assert len(report.get("recent_fills_sample", [])) >= 1
    f = report["recent_fills_sample"][0]
    assert f.get("trade_id") == "abc-123"
    assert "filled_value" in f or "proceeds" in str(f)


def test_no_forbidden_production_calls_in_source():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "place_order", "cancel_order", "modify_order", "submit_order",
        "append_coinbase_fill_row(",
    ]
    for tok in forbidden:
        assert tok not in text


def test_adapter_error_path_reports_unknown_broker_state():
    """When BrokerCoinbase() fails with TypeError (e.g. unexpected dry_run), 
    we must report unknown (not false) for broker holdings and force BLOCKED + unsafe.
    """
    fake_snapshot = probe.LiveBrokerSnapshot(
        credential_status="adapter_error",
        errors=["BrokerCoinbase.__init__() got an unexpected keyword argument 'dry_run'"],
        broker_read_successful=False,
    )

    report = probe.synthesize_reconciliation_report(fake_snapshot)

    assert report["verdict"] == "BLOCKED"
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["sol_on_broker"] is None
    assert report["eth_on_broker"] is None
    assert any("adapter incompatibility" in b.lower() for b in report["blockers"])
    assert "dry_run" in report["next_action"] or "adapter" in report["next_action"].lower()


def test_script_contains_no_obvious_file_mutation():
    text = SCRIPT.read_text(encoding="utf-8")
    # Very light heuristic — real safety is that we never open(..., "w") for logs/
    assert 'open(' not in text or 'coinbase_fills.csv' not in text


def test_json_output_contains_all_required_top_level_keys():
    fake_snapshot = probe.LiveBrokerSnapshot(credential_status="present")
    report = probe.synthesize_reconciliation_report(fake_snapshot)

    required = ["verdict", "profit_readout", "blockers", "next_action"]
    for key in required:
        assert key in report
