import importlib.util
import json
import shutil
import sys
import unittest.mock as mock
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coinbase_broker_readonly_reconciler.py"
STATE_FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_manual_review_blocker_watchdog"
BROKER_FIXTURES = ROOT / "tests" / "fixtures" / "coinbase_broker_readonly_reconcile"

spec = importlib.util.spec_from_file_location("coinbase_broker_readonly_reconciler", SCRIPT)
reconciler = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reconciler
spec.loader.exec_module(reconciler)


def copy_root(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(STATE_FIXTURE, target, dirs_exist_ok=True)
    (target / "config_coinbase_crypto.yaml").write_text(
        "global_risk:\n"
        "  max_open_positions: 1\n"
        "  max_trades_per_day: 3\n"
        "crypto:\n"
        "  max_trade_notional_usd: 10.0\n"
        "  absolute_hard_trade_cap_usd: 10.0\n",
        encoding="utf-8",
    )
    # Ensure runtime dir exists for STOP_TRADING check
    (target / "runtime").mkdir(parents=True, exist_ok=True)
    return target


def broker(name: str) -> dict:
    return json.loads((BROKER_FIXTURES / name).read_text(encoding="utf-8"))


def healthy_heartbeat() -> dict:
    return {
        "heartbeat_fresh": True,
        "duplicate_live_process_risk": False,
        "lock_health": "OK",
        "file_alerting_active": True,
    }


def test_ada_local_open_broker_flat_is_clear_candidate(tmp_path):
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=healthy_heartbeat(),
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
    )
    ada = report["reconciled_symbols"]["ADA/USD"]
    assert ada["classification"] == "local_open_broker_flat"
    assert report["ada_clear_candidate"] is True
    assert report["safe_to_clear_local_ada"] is True


def test_ada_open_at_broker_refuses_clear(tmp_path):
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_ada_open.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["reconciled_symbols"]["ADA/USD"]["classification"] == "local_open_broker_open"
    assert report["ada_clear_candidate"] is False
    assert report["safe_to_clear_local_ada"] is False
    assert report["resume_micro_trading_go_no_go"] == "NO_GO"


def test_unknown_broker_truth_refuses_clear_and_resume(tmp_path):
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_unknown.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["reconciled_symbols"]["ADA/USD"]["classification"] == "unknown"
    assert report["ada_clear_candidate"] is False
    assert report["safe_to_clear_local_ada"] is False
    assert "broker_truth_unknown_live_read_only_required" in report["reasons"]


def test_sol_external_inventory_is_classified_separately(tmp_path):
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["reconciled_symbols"]["SOL/USD"]["classification"] == "local_external_inventory_only"
    assert "SOL/USD" in report["local_external_inventory"]


def test_duplicate_process_forces_no_go(tmp_path):
    heartbeat = healthy_heartbeat()
    heartbeat["duplicate_live_process_risk"] = True
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=heartbeat,
    )
    assert report["resume_micro_trading_go_no_go"] == "NO_GO"
    assert report["ada_clear_candidate"] is True
    assert report["safe_to_clear_local_ada"] is False
    assert "duplicate_live_process_risk" in report["reasons"]


def test_ready_for_operator_approval_requires_flat_local_and_broker(tmp_path):
    # ADA flat fixture has local ADA open, so GO should be NO_GO
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["resume_micro_trading_go_no_go"] == "NO_GO"
    assert report["safe_to_resume_micro_trading"] is False

    # Simulate fully flat state (no local open positions)
    root = copy_root(tmp_path)
    (root / "state" / "coinbase" / "open_positions.json").write_text('{"positions": {}}')

    report = reconciler.build_report(
        repo_root=root,
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["resume_micro_trading_go_no_go"] == "GO"
    assert report["safe_to_resume_micro_trading"] == "READY_FOR_OPERATOR_APPROVAL"


def test_default_mode_does_not_mutate_state(tmp_path):
    root = copy_root(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    reconciler.build_report(
        repo_root=root,
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_mutation_flags_are_always_false(tmp_path):
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["order_mutation_performed"] is False
    assert report["state_mutation_performed"] is False
    assert report["restart_performed"] is False


def test_no_secrets_in_report(tmp_path):
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    report_json = json.dumps(report)
    for forbidden in ("secret", "api_key", "CB-ACCESS", "Bearer"):
        assert forbidden not in report_json


def test_live_read_only_default_calls_false():
    # Verify default main doesn't call broker
    with mock.patch("scripts.coinbase_broker_readonly_reconciler.fetch_live_coinbase_data") as mock_fetch:
        reconciler.main(["--repo-root", str(ROOT)])
        mock_fetch.assert_not_called()


def test_ada_dust_threshold(tmp_path):
    # If ADA is 0.5 (below 1.0 threshold), it's considered flat for ADA_PRESENT but not for READY_FOR_RESUME
    payload = broker("broker_ada_flat.json")
    payload["balances"] = [{"asset": "ADA", "available": "0.5"}]

    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=payload,
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["ada_broker_present"] is False
    assert report["ada_clear_candidate"] is True # Still local blocker

    # But if there's an open order, it's not flat
    payload["open_orders"] = [{"product_id": "ADA-USD", "side": "buy", "status": "OPEN"}]
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=payload,
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["ada_clear_candidate"] is False
    assert "ada_broker_exposure_or_open_order_still_present" in report["reasons"]
