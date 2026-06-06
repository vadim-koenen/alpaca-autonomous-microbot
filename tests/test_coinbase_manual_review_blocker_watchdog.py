import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coinbase_manual_review_blocker_watchdog.py"
FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_manual_review_blocker_watchdog"

spec = importlib.util.spec_from_file_location("coinbase_manual_review_blocker_watchdog", SCRIPT)
watchdog = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = watchdog
spec.loader.exec_module(watchdog)


def fixture_paths(root: Path) -> dict:
    return {
        "root": root,
        "journal": root / "journal_coinbase_crypto.csv",
        "open_positions": root / "state" / "coinbase" / "open_positions.json",
        "external_inventory": root / "state" / "coinbase" / "external_inventory.json",
        "closed_positions": root / "state" / "coinbase" / "closed_positions.json",
        "lock": root / "runtime" / "coinbase.lock",
        "stop": root / "runtime" / "STOP_TRADING",
        "backup_dir": root / "state" / "coinbase" / "backups",
        "audit_dir": root / "reports" / "blocker_remediation",
    }


def copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "fixture"
    shutil.copytree(FIXTURE, target)
    return target


def test_detects_ada_zombie_blocker_duplicate_process_and_24h_escalation():
    report = watchdog.build_report(
        paths=fixture_paths(FIXTURE),
        process_snapshot=FIXTURE / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids={99999999},
    )

    assert report["blockers_detected"] is True
    assert report["active_blocker_count"] == 1
    assert report["primary_blocker_symbol"] == "ADA/USD"
    assert report["blocker_age_hours"] == 48.0
    assert report["recent_entry_blocked_count"] == 3
    assert report["duplicate_live_process_risk"] is True
    assert report["runtime_lock_active"] is True
    assert report["bot_blocked_but_still_running"] is True
    assert report["alert_severity"] == "CRITICAL"
    assert "blocked_duration_exceeds_24_hours" in report["alert_flags"]
    assert report["last_entry_or_fill_event"]["symbol"] == "ADA/USD"
    assert report["last_close_failure"]["symbol"] == "ADA/USD"
    assert report["last_broker_reassociated_warning"]["symbol"] == "ADA/USD"


def test_external_staked_sol_is_reported_but_not_counted_as_active_bot_blocker():
    report = watchdog.build_report(
        paths=fixture_paths(FIXTURE),
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids=set(),
    )

    assert report["active_blocker_count"] == 1
    assert report["external_inventory_blocker_symbols"] == ["SOL/USD"]
    assert report["primary_blocker_symbol"] == "ADA/USD"


def test_default_mode_is_read_only(tmp_path):
    root = copy_fixture(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    watchdog.build_report(
        paths=fixture_paths(root),
        process_snapshot=root / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids={99999999},
    )

    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_plan_mode_produces_steps_without_mutation(tmp_path):
    root = copy_fixture(tmp_path)
    paths = fixture_paths(root)
    before = paths["open_positions"].read_bytes()
    report = watchdog.build_report(
        paths=paths,
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids=set(),
    )
    plan = watchdog.remediation_plan(report, paths)

    assert any("stop_all_verified.sh" in step for step in plan)
    assert any("--operator-confirmed-no-broker-position" in step for step in plan)
    assert before == paths["open_positions"].read_bytes()


def test_clear_refuses_running_process_missing_confirmation_and_missing_stop(tmp_path):
    root = copy_fixture(tmp_path)
    result = watchdog.clear_local_stale_blocker(
        paths=fixture_paths(root),
        symbol="ADA/USD",
        reason="verified",
        operator_confirmed=False,
        process_snapshot=root / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids={99999999},
    )

    assert result["remediation_performed"] is False
    assert "stop_trading_kill_switch_required" in result["refusal_reasons"]
    assert "live_bot_process_still_running" in result["refusal_reasons"]
    assert "runtime_lock_pid_still_active" in result["refusal_reasons"]
    assert "operator_confirmation_required" in result["refusal_reasons"]


def test_clear_refuses_symbol_mismatch(tmp_path):
    root = copy_fixture(tmp_path)
    (root / "runtime" / "STOP_TRADING").touch()
    (root / "process_snapshot.txt").write_text("", encoding="utf-8")
    result = watchdog.clear_local_stale_blocker(
        paths=fixture_paths(root),
        symbol="ETH/USD",
        reason="operator verified",
        operator_confirmed=True,
        process_snapshot=root / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids=set(),
    )

    assert result["remediation_performed"] is False
    assert "exactly_one_matching_manual_review_position_required" in result["refusal_reasons"]


def test_guarded_clear_backups_audits_and_only_removes_intended_symbol(tmp_path):
    root = copy_fixture(tmp_path)
    paths = fixture_paths(root)
    paths["stop"].touch()
    (root / "process_snapshot.txt").write_text("", encoding="utf-8")

    result = watchdog.clear_local_stale_blocker(
        paths=paths,
        symbol="ADA/USD",
        reason="operator verified no broker position or open order",
        operator_confirmed=True,
        process_snapshot=root / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids=set(),
    )

    assert result["remediation_performed"] is True
    assert Path(result["backup_path"]).exists()
    assert Path(result["audit_path"]).exists()
    open_after = json.loads(paths["open_positions"].read_text(encoding="utf-8"))
    assert set(open_after["positions"]) == {"BTC/USD"}
    closed_after = json.loads(paths["closed_positions"].read_text(encoding="utf-8"))
    archived = next(iter(closed_after["positions"].values()))
    assert archived["symbol"] == "ADA/USD"
    assert archived["broker_truth_claimed"] is False
    audit = json.loads(Path(result["audit_path"]).read_text(encoding="utf-8"))
    assert audit["broker_calls_made"] is False
    assert audit["unrelated_symbols_preserved"] == ["BTC/USD"]


def test_authorizations_are_false_in_default_output():
    report = watchdog.build_report(
        paths=fixture_paths(FIXTURE),
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids=set(),
    )
    for key, expected in watchdog.AUTHORIZATION_DEFAULTS.items():
        assert report[key] is expected
    assert report["safe_to_clear_local_state"] is False


def test_strict_exit_code_only_fails_when_requested():
    common = [
        sys.executable,
        str(SCRIPT),
        "--repo-root",
        str(FIXTURE),
        "--process-snapshot",
        str(FIXTURE / "process_snapshot.txt"),
        "--now",
        "2026-06-06T12:00:00+00:00",
        "--json",
    ]
    default = subprocess.run(common, check=False, capture_output=True, text=True)
    strict = subprocess.run(common + ["--strict-exit-code"], check=False, capture_output=True, text=True)
    assert default.returncode == 0
    assert strict.returncode == 2


def test_script_has_no_broker_network_auth_or_order_hooks():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = (
        "broker_coinbase",
        "requests.",
        "urllib.",
        "load_dotenv",
        "create_order",
        "place_order",
        "cancel_order",
        "close_position",
        "append_coinbase_fill_row",
        "launchctl",
    )
    for token in forbidden:
        assert token not in text
