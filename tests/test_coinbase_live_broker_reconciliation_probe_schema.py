# ADVISORY ONLY — schema hardening tests for the live broker probe (P2-017A)

import json
from pathlib import Path
import importlib.util
import sys
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_live_broker_reconciliation_probe.py"
spec = importlib.util.spec_from_file_location("probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def test_default_no_live_includes_explicit_booleans():
    """Default mode (no --live-read-only) must include the three explicit booleans set correctly."""
    report = probe._build_safe_default_report()
    assert report["live_read_only"] is False
    assert report["broker_calls_made"] is False
    assert report["broker_read_successful"] is False


def test_mocked_live_success_sets_booleans_true():
    """When a live read succeeds, the three booleans must be true."""
    fake_snapshot = probe.LiveBrokerSnapshot(
        credential_status="present",
        broker_read_successful=True,
    )
    report = probe.synthesize_reconciliation_report(fake_snapshot)
    assert report["live_read_only"] is True
    assert report["broker_calls_made"] is True
    assert report["broker_read_successful"] is True


def test_mocked_broker_failure_keeps_broker_facts_unknown():
    """On broker failure, sol_on_broker / eth_on_broker must remain None (not false)."""
    fake_snapshot = probe.LiveBrokerSnapshot(
        credential_status="missing_or_blocked",
        broker_read_successful=False,
    )
    report = probe.synthesize_reconciliation_report(fake_snapshot)
    assert report["sol_on_broker"] is None
    assert report["eth_on_broker"] is None
    assert report["broker_read_successful"] is False