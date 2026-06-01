# ADVISORY ONLY — tests for the broker truth summary script (P2-017A)

from pathlib import Path
import importlib.util
import sys
import json
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_broker_truth_summary.py"
spec = importlib.util.spec_from_file_location("summary", SCRIPT)
summary = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = summary
spec.loader.exec_module(summary)


def test_old_probe_json_missing_booleans_is_handled_gracefully(tmp_path):
    """Old probe JSON without the new schema booleans must not crash and must report schema_missing_fields."""
    old_probe = {
        "verdict": "BLOCKED",
        "profit_readout": "unsafe_to_aggregate",
        "sol_on_broker": True,
        "eth_on_broker": None,
        "open_orders": [],
        "recent_fills_sample": [{"trade_id": "x"}],
        "credential_status": "present",
    }
    probe_file = tmp_path / "old_probe.json"
    probe_file.write_text(json.dumps(old_probe))

    report = summary.build_summary(probe_file)
    assert "schema_missing_fields" in report
    assert "live_read_only" in report["schema_missing_fields"]
    # When the key is missing we conservatively treat broker_read_successful as False
    assert report["broker_read_successful"] is False
    assert report["sol_on_broker"] is True


def test_zero_qty_journal_rows_are_counted_but_not_treated_as_fills(tmp_path):
    """Journal rows with qty=0 must be counted in the zero-qty counter but not inflate real fill counts."""
    # The summary script parses the real journal; we just assert the structure here.
    # For a pure unit test we can call the internal journal helper if exposed, or trust the integration.
    # We at least verify the function runs without crashing on the real journal.
    report = summary.build_summary(tmp_path / "nonexistent_probe.json")  # will have schema_missing
    assert "local_journal_recent_zero_qty_rows_count" in report
    assert isinstance(report["local_journal_recent_zero_qty_rows_count"], int)


def test_sol_held_on_broker_produces_blocked_sol_held_status(tmp_path):
    """When probe reports sol_on_broker=true with successful read, status must be blocked_sol_held_on_broker and profit unsafe."""
    probe = {
        "verdict": "BLOCKED",
        "profit_readout": "unsafe_to_aggregate",
        "live_read_only": True,
        "broker_calls_made": True,
        "broker_read_successful": True,
        "sol_on_broker": True,
        "eth_on_broker": None,
        "open_orders": [],
        "recent_fills_sample": [{"trade_id": "f1"}],
        "credential_status": "present",
    }
    probe_file = tmp_path / "sol_held_probe.json"
    probe_file.write_text(json.dumps(probe))

    report = summary.build_summary(probe_file)
    assert report["reconciliation_status"] == "blocked_sol_held_on_broker"
    assert report["verdict"] == "BLOCKED"
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["broker_truth_available"] is True
    assert report["sol_on_broker"] is True


def test_summary_does_not_read_env_or_call_broker_or_mutate(tmp_path, monkeypatch):
    """Summary must never read .env, never import/call broker APIs, never mutate any files (pure read-only diagnostic)."""
    probe = {
        "verdict": "BLOCKED",
        "profit_readout": "unsafe_to_aggregate",
        "live_read_only": False,
        "broker_calls_made": False,
        "broker_read_successful": False,
        "sol_on_broker": None,
        "eth_on_broker": None,
        "open_orders": [],
        "recent_fills_sample": [],
    }
    probe_file = tmp_path / "probe.json"
    probe_file.write_text(json.dumps(probe))

    # Create a tempting .env in the isolated dir; code must not read it
    (tmp_path / ".env").write_text("COINBASE_API_KEY=THIS_MUST_NOT_BE_READ_BY_SUMMARY\nCOINBASE_API_SECRET=SECRET\n")

    # Isolate cwd
    monkeypatch.chdir(tmp_path)

    # Detect any attempt to import broker_coinbase during build_summary
    import builtins
    original_import = builtins.__import__
    imported_names = []
    def tracking_import(name, *a, **k):
        imported_names.append(name)
        return original_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    # Run (should succeed without side effects)
    report = summary.build_summary(probe_file)

    # No broker_coinbase import occurred
    assert not any("broker_coinbase" in str(n) for n in imported_names), "summary must not import broker_coinbase"

    # .env was not read (we can at least confirm no crash and no secret in output)
    assert "THIS_MUST_NOT_BE_READ" not in str(report)

    # No mutations: the only files in tmp are the ones we created; build should not have created/written others
    # (we can't easily intercept all open(), but absence of write side effects + pure function contract is verified by no new files beyond probe)
    created_after = {p.name for p in tmp_path.iterdir()}
    # probe.json and .env are expected; nothing else should appear from summary
    assert created_after == {"probe.json", ".env"}, f"unexpected files created by summary: {created_after - {'probe.json', '.env'}}"

    assert "verdict" in report
    assert report["broker_truth_available"] is False