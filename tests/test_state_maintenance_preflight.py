import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "state_maintenance_preflight.py"


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_broker_state(tmp_path, broker, open_positions=None, closed_positions=None):
    _write_json(
        tmp_path / "state" / broker / "open_positions.json",
        {"state_namespace": broker, "positions": open_positions or {}},
    )
    _write_json(
        tmp_path / "state" / broker / "closed_positions.json",
        {"state_namespace": broker, "positions": closed_positions or {}},
    )


def _run_preflight(tmp_path):
    env = os.environ.copy()
    env["BOT_DIR_OVERRIDE"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_preflight_json(tmp_path):
    env = os.environ.copy()
    env["BOT_DIR_OVERRIDE"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_init_missing(tmp_path):
    env = os.environ.copy()
    env["BOT_DIR_OVERRIDE"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--init-missing"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_normalize_state(tmp_path):
    env = os.environ.copy()
    env["BOT_DIR_OVERRIDE"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--normalize-state"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _state_hashes(tmp_path):
    hashes = {}
    for path in sorted((tmp_path / "state").rglob("*.json")):
        hashes[path.relative_to(tmp_path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def test_preflight_valid_state_with_no_recovered_positions_is_ok(tmp_path):
    _write_broker_state(tmp_path, "coinbase")
    _write_broker_state(tmp_path, "alpaca")

    result = _run_preflight(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "overall_status=OK" in result.stdout
    assert "broker_recovered=0" in result.stdout
    assert "Suggested cleanup commands:\n- none" in result.stdout


def test_preflight_empty_object_state_files_are_valid(tmp_path):
    for broker in ("coinbase", "alpaca"):
        state_dir = tmp_path / "state" / broker
        state_dir.mkdir(parents=True)
        (state_dir / "open_positions.json").write_text("{}\n", encoding="utf-8")
        (state_dir / "closed_positions.json").write_text("{}\n", encoding="utf-8")

    result = _run_preflight(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "overall_status=OK" in result.stdout
    assert "positions=0" in result.stdout


def test_preflight_missing_closed_positions_reports_warn_read_only(tmp_path):
    _write_broker_state(tmp_path, "coinbase")
    _write_json(
        tmp_path / "state" / "alpaca" / "open_positions.json",
        {"state_namespace": "alpaca", "positions": {}},
    )

    result = _run_preflight(tmp_path)

    assert result.returncode == 1
    assert "overall_status=WARN" in result.stdout
    assert "state/alpaca/closed_positions.json: status=WARN valid=false missing=true" in result.stdout
    assert "python3 scripts/state_maintenance_preflight.py --init-missing" in result.stdout
    assert not (tmp_path / "state" / "alpaca" / "closed_positions.json").exists()


def test_preflight_json_emits_valid_schema(tmp_path):
    _write_broker_state(tmp_path, "coinbase")
    _write_broker_state(tmp_path, "alpaca")

    result = _run_preflight_json(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "OK"
    assert "generated_at" in payload
    assert payload["brokers"]["coinbase"]["open_positions_count"] == 0
    assert payload["brokers"]["coinbase"]["closed_positions_count"] == 0
    assert payload["brokers"]["coinbase"]["broker_recovered_open_count"] == 0
    assert payload["brokers"]["coinbase"]["non_controllable_open_count"] == 0
    assert payload["brokers"]["coinbase"]["missing_counts_toward_exposure_count"] == 0
    assert payload["brokers"]["alpaca"]["open_positions_count"] == 0
    assert payload["runtime"]["coinbase"]["status"] == "OK"
    assert payload["runtime"]["alpaca"]["status"] == "OK"
    assert payload["suggested_cleanup_commands"] == []
    assert payload["suggested_state_init_commands"] == []
    assert payload["missing_state_files"] == []
    assert payload["warnings"] == []
    assert payload["action_required_items"] == []


def test_preflight_recovered_position_prints_suggested_clear_command(tmp_path):
    _write_broker_state(
        tmp_path,
        "coinbase",
        open_positions={
            "ETH/USD": {
                "asset_class": "crypto",
                "order_status": "broker_recovered",
                "api_controllable": False,
                "exit_evaluation_enabled": False,
            }
        },
    )
    _write_broker_state(tmp_path, "alpaca")

    result = _run_preflight(tmp_path)

    assert result.returncode == 1
    assert "overall_status=ACTION_REQUIRED" in result.stdout
    assert "coinbase ETH/USD: status=ACTION_REQUIRED" in result.stdout
    assert (
        "bash scripts/clear_recovered_position.sh --broker coinbase "
        "--key 'ETH/USD' --reason '<operator verified reason>'"
    ) in result.stdout
    assert "No cleanup was executed." in result.stdout


def test_preflight_json_includes_suggestions_only_for_recovered_open_positions(tmp_path):
    _write_broker_state(
        tmp_path,
        "coinbase",
        open_positions={
            "ETH/USD": {
                "asset_class": "crypto",
                "order_status": "broker_recovered",
                "api_controllable": False,
                "exit_evaluation_enabled": False,
            },
            "BTC/USD": {
                "asset_class": "crypto",
                "order_status": "filled",
                "api_controllable": True,
            },
        },
        closed_positions={
            "SOL/USD": {
                "asset_class": "crypto",
                "order_status": "broker_recovered",
            }
        },
    )
    _write_broker_state(tmp_path, "alpaca")

    result = _run_preflight_json(tmp_path)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "ACTION_REQUIRED"
    assert payload["brokers"]["coinbase"]["open_positions_count"] == 2
    assert payload["brokers"]["coinbase"]["closed_positions_count"] == 1
    assert payload["brokers"]["coinbase"]["broker_recovered_open_count"] == 1
    assert payload["brokers"]["coinbase"]["non_controllable_open_count"] == 1
    assert payload["brokers"]["coinbase"]["missing_counts_toward_exposure_count"] == 2
    assert len(payload["suggested_cleanup_commands"]) == 1
    assert "--key 'ETH/USD'" in payload["suggested_cleanup_commands"][0]
    assert "SOL/USD" not in payload["suggested_cleanup_commands"][0]
    assert len(payload["action_required_items"]) == 1


def test_preflight_bot_position_missing_safety_fields_warns_with_normalization_command(tmp_path):
    _write_broker_state(
        tmp_path,
        "coinbase",
        open_positions={
            "BTC/USD": {
                "asset_class": "crypto",
                "order_status": "filled",
                "order_id": "bot-order",
                "notional": 0.50,
            }
        },
    )
    _write_broker_state(tmp_path, "alpaca")

    result = _run_preflight(tmp_path)

    assert result.returncode == 1
    assert "overall_status=WARN" in result.stdout
    assert "ACTION_REQUIRED" not in result.stdout
    assert "missing_counts_toward_exposure=1" in result.stdout
    assert "python3 scripts/state_maintenance_preflight.py --normalize-state" in result.stdout


def test_normalize_state_backfills_bot_position_and_preserves_false(tmp_path):
    _write_broker_state(
        tmp_path,
        "coinbase",
        open_positions={
            "BTC/USD": {
                "asset_class": "crypto",
                "order_status": "filled",
                "order_id": "bot-order",
                "notional": 0.50,
            },
            "SOL/USD": {
                "asset_class": "crypto",
                "order_status": "filled",
                "order_id": "bot-order-2",
                "notional": 0.50,
                "counts_toward_exposure": False,
            },
        },
    )
    _write_broker_state(tmp_path, "alpaca")

    result = _run_normalize_state(tmp_path)

    assert result.returncode == 0, result.stdout
    state = json.loads(
        (tmp_path / "state" / "coinbase" / "open_positions.json").read_text(encoding="utf-8")
    )
    btc = state["positions"]["BTC/USD"]
    sol = state["positions"]["SOL/USD"]
    assert btc["counts_toward_exposure"] is True
    assert btc["api_controllable"] is True
    assert btc["bot_opened"] is True
    assert btc["exit_evaluation_enabled"] is True
    assert btc["user_action_required"] is False
    assert sol["counts_toward_exposure"] is False


def test_preflight_invalid_json_reports_blocked_manual_review(tmp_path):
    _write_broker_state(tmp_path, "alpaca")
    state_dir = tmp_path / "state" / "coinbase"
    state_dir.mkdir(parents=True)
    (state_dir / "open_positions.json").write_text("{not json", encoding="utf-8")
    _write_json(state_dir / "closed_positions.json", {"positions": {}})

    result = _run_preflight(tmp_path)

    assert result.returncode == 2
    assert "overall_status=BLOCKED_MANUAL_REVIEW" in result.stdout
    assert "state/coinbase/open_positions.json: status=BLOCKED_MANUAL_REVIEW valid=false" in result.stdout
    assert "invalid JSON" in result.stdout


def test_preflight_json_invalid_state_reports_blocked_manual_review(tmp_path):
    _write_broker_state(tmp_path, "alpaca")
    state_dir = tmp_path / "state" / "coinbase"
    state_dir.mkdir(parents=True)
    (state_dir / "open_positions.json").write_text("{not json", encoding="utf-8")
    _write_json(state_dir / "closed_positions.json", {"positions": {}})

    result = _run_preflight_json(tmp_path)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "BLOCKED_MANUAL_REVIEW"
    assert any("invalid JSON" in warning for warning in payload["warnings"])


def test_init_missing_creates_only_missing_files(tmp_path):
    _write_broker_state(tmp_path, "coinbase")
    _write_json(
        tmp_path / "state" / "alpaca" / "open_positions.json",
        {"state_namespace": "alpaca", "positions": {}},
    )
    existing_before = _state_hashes(tmp_path)

    result = _run_init_missing(tmp_path)

    assert result.returncode == 0, result.stderr
    created = tmp_path / "state" / "alpaca" / "closed_positions.json"
    assert created.read_text(encoding="utf-8") == "{}\n"
    existing_after = _state_hashes(tmp_path)
    for path, digest in existing_before.items():
        assert existing_after[path] == digest
    assert "state/alpaca/closed_positions.json" in result.stdout


def test_init_missing_does_not_overwrite_existing_files(tmp_path):
    _write_broker_state(tmp_path, "coinbase")
    _write_broker_state(tmp_path, "alpaca")
    before = _state_hashes(tmp_path)

    result = _run_init_missing(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _state_hashes(tmp_path) == before
    assert "created_files: none" in result.stdout


def test_init_missing_running_bot_blocks_mutation(tmp_path):
    _write_broker_state(tmp_path, "coinbase")
    _write_json(
        tmp_path / "state" / "alpaca" / "open_positions.json",
        {"state_namespace": "alpaca", "positions": {}},
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "coinbase.lock").write_text(str(os.getpid()), encoding="utf-8")

    result = _run_init_missing(tmp_path)

    assert result.returncode == 2
    assert "refusing --init-missing" in result.stdout
    assert not (tmp_path / "state" / "alpaca" / "closed_positions.json").exists()


def test_init_missing_invalid_json_is_not_overwritten(tmp_path):
    _write_broker_state(tmp_path, "alpaca")
    state_dir = tmp_path / "state" / "coinbase"
    state_dir.mkdir(parents=True)
    invalid_path = state_dir / "open_positions.json"
    invalid_path.write_text("{not json", encoding="utf-8")
    missing_path = state_dir / "closed_positions.json"

    result = _run_init_missing(tmp_path)

    assert result.returncode == 2
    assert invalid_path.read_text(encoding="utf-8") == "{not json"
    assert not missing_path.exists()
    assert "is invalid" in result.stdout


def test_preflight_running_bot_blocks_immediate_clear_recommendation(tmp_path):
    _write_broker_state(
        tmp_path,
        "coinbase",
        open_positions={
            "ETH/USD": {
                "asset_class": "crypto",
                "order_status": "broker_recovered",
            }
        },
    )
    _write_broker_state(tmp_path, "alpaca")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "coinbase.lock").write_text(str(os.getpid()), encoding="utf-8")

    result = _run_preflight(tmp_path)

    assert result.returncode == 2
    assert "overall_status=BLOCKED_MANUAL_REVIEW" in result.stdout
    assert "coinbase ETH/USD: status=BLOCKED_MANUAL_REVIEW" in result.stdout
    assert "Do not run while this bot appears to be running." in result.stdout
    assert "clear_recovered_position.sh --broker coinbase" in result.stdout


def test_preflight_does_not_mutate_state_files(tmp_path):
    _write_broker_state(
        tmp_path,
        "coinbase",
        open_positions={
            "ETH/USD": {
                "asset_class": "crypto",
                "order_status": "broker_recovered",
            }
        },
    )
    _write_broker_state(tmp_path, "alpaca")
    before = _state_hashes(tmp_path)

    result = _run_preflight(tmp_path)

    assert result.returncode == 1
    assert _state_hashes(tmp_path) == before
    assert "No cleanup was executed." in result.stdout


def test_preflight_json_does_not_mutate_state_files(tmp_path):
    _write_broker_state(
        tmp_path,
        "coinbase",
        open_positions={
            "ETH/USD": {
                "asset_class": "crypto",
                "order_status": "broker_recovered",
            }
        },
    )
    _write_broker_state(tmp_path, "alpaca")
    before = _state_hashes(tmp_path)

    result = _run_preflight_json(tmp_path)

    assert result.returncode == 1
    assert _state_hashes(tmp_path) == before
    assert json.loads(result.stdout)["suggested_cleanup_commands"]


def test_uncertain_broker_recovered_position_remains_blocked_when_bot_running(tmp_path):
    _write_broker_state(
        tmp_path,
        "coinbase",
        open_positions={
            "BTC/USD": {
                "asset_class": "crypto",
                "strategy": "recovered",
                "order_status": "broker_recovered",
                "api_controllable": False,
                "exit_evaluation_enabled": False,
                "counts_toward_exposure": True,
            }
        },
    )
    _write_broker_state(tmp_path, "alpaca")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "coinbase.lock").write_text(str(os.getpid()), encoding="utf-8")

    result = _run_preflight_json(tmp_path)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "BLOCKED_MANUAL_REVIEW"
    assert payload["brokers"]["coinbase"]["broker_recovered_open_count"] == 1
    assert payload["action_required_items"]


def test_preflight_scripts_have_no_live_or_broker_actions():
    combined = (
        (ROOT / "scripts" / "state_maintenance_preflight.py").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "scripts" / "state_maintenance_preflight.sh").read_text(encoding="utf-8")
    )
    forbidden = [
        "launchctl",
        "main.py --mode live",
        "place_order",
        "place_market_order",
        "place_limit_order",
        "cancel_order",
        "submit_order",
    ]
    for token in forbidden:
        assert token not in combined
