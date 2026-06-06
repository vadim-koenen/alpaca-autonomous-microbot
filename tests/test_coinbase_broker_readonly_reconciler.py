import importlib.util
import json
import shutil
import sys
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
    shutil.copytree(STATE_FIXTURE, target)
    (target / "config_coinbase_crypto.yaml").write_text(
        "global_risk:\n"
        "  max_open_positions: 1\n"
        "  max_trades_per_day: 3\n"
        "crypto:\n"
        "  max_trade_notional_usd: 10.0\n"
        "  absolute_hard_trade_cap_usd: 10.0\n",
        encoding="utf-8",
    )
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
    assert "broker_truth_unknown_fixture_or_captured_json_required" in report["reasons"]


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


def test_go_requires_all_operational_gates(tmp_path):
    report = reconciler.build_report(
        repo_root=copy_root(tmp_path),
        broker_payload=broker("broker_ada_flat.json"),
        heartbeat_report=healthy_heartbeat(),
    )
    assert report["resume_micro_trading_go_no_go"] == "GO"
    assert report["safe_to_resume_micro_trading"] is True
    assert report["live_trading_authorized"] is False
    assert report["state_clear_authorized"] is False
    assert report["scaling_authorized"] is False


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


def test_real_broker_integration_is_disabled_pending_credential_review():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "BrokerCoinbase" not in text
    assert "broker_coinbase" not in text
    assert "fixture_or_captured_json_only_pending_credential_boundary_review" in text
    for token in ("create_order", "place_order", "cancel_order", "close_position", "load_dotenv"):
        assert token not in text
