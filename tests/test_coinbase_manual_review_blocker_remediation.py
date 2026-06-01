# ADVISORY ONLY - P2-021C3 offline manual-review blocker remediation tests.
# No broker calls, no credential reads, no order activity, no state writes except
# temporary roots explicitly created by tests.

import json
import shutil
from pathlib import Path
import importlib.util
import sys

from utils import calculate_crypto_entry_blockers


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coinbase_manual_review_blocker_remediation.py"
FIXTURES = ROOT / "tests" / "fixtures" / "coinbase_manual_review_blocker"

spec = importlib.util.spec_from_file_location("coinbase_manual_review_blocker_remediation", SCRIPT)
remediation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = remediation
spec.loader.exec_module(remediation)


def _copy_state(tmp_path: Path, fixture_name: str) -> Path:
    source = FIXTURES / fixture_name
    target = tmp_path / fixture_name
    shutil.copytree(source, target)
    return target


def _positions(root: Path) -> dict:
    return json.loads((root / "state" / "coinbase" / "open_positions.json").read_text())["positions"]


def test_default_dry_run_makes_no_writes(tmp_path):
    state_root = _copy_state(tmp_path, "manual_review_sol_state")
    before = (state_root / "state" / "coinbase" / "open_positions.json").read_text()

    report = remediation.build_report(
        state_root=state_root,
        assertion_json=FIXTURES / "external_staked_sol_assertion.json",
    )

    after = (state_root / "state" / "coinbase" / "open_positions.json").read_text()
    assert report["verdict"] == "DRY_RUN_READY_FOR_OPERATOR_APPROVAL"
    assert report["safe_to_normalize"] is True
    assert report["apply_required"] is True
    assert report["trading_block_would_clear"] is True
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert before == after
    assert not (state_root / "state" / "coinbase" / "external_inventory.json").exists()


def test_apply_without_operator_approval_refuses(tmp_path):
    state_root = _copy_state(tmp_path, "manual_review_sol_state")

    report = remediation.build_report(
        state_root=state_root,
        assertion_json=FIXTURES / "external_staked_sol_assertion.json",
        apply=True,
        operator_approved=False,
    )

    assert report["verdict"] == "NOT_SAFE_TO_NORMALIZE"
    assert "operator_approval_flag_missing_during_apply" in report["refusal_reasons"]
    assert "SOL/USD" in _positions(state_root)


def test_api_controllable_true_position_refuses(tmp_path):
    state_root = _copy_state(tmp_path, "manual_review_api_controllable")

    report = remediation.build_report(
        state_root=state_root,
        assertion_json=FIXTURES / "external_staked_sol_assertion.json",
    )

    assert report["verdict"] == "NOT_SAFE_TO_NORMALIZE"
    assert "api_controllable_position_refuses_normalization" in report["refusal_reasons"]


def test_multiple_unresolved_positions_refuse(tmp_path):
    state_root = _copy_state(tmp_path, "manual_review_sol_state_multi")

    report = remediation.build_report(
        state_root=state_root,
        assertion_json=FIXTURES / "external_staked_sol_assertion.json",
    )

    assert report["verdict"] == "NOT_SAFE_TO_NORMALIZE"
    assert "exactly_one_blocking_manual_review_position_required" in report["refusal_reasons"]


def test_no_external_or_staked_evidence_refuses(tmp_path):
    state_root = _copy_state(tmp_path, "manual_review_sol_state_no_assertion")

    report = remediation.build_report(state_root=state_root)

    assert report["verdict"] == "NOT_SAFE_TO_NORMALIZE"
    assert "external_staked_non_bot_inventory_evidence_missing" in report["refusal_reasons"]


def test_external_staked_sol_with_operator_assertion_can_normalize(tmp_path):
    state_root = _copy_state(tmp_path, "manual_review_sol_state")

    report = remediation.build_report(
        state_root=state_root,
        assertion_json=FIXTURES / "external_staked_sol_assertion.json",
        apply=True,
        operator_approved=True,
    )

    assert report["verdict"] == "NORMALIZED_EXTERNAL_INVENTORY"
    assert report["safe_to_normalize"] is True
    assert report["trading_block_would_clear"] is True
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert "SOL/USD" not in _positions(state_root)

    external = json.loads((state_root / "state" / "coinbase" / "external_inventory.json").read_text())
    record = external["external_inventory"]["SOL/USD"]
    assert record["operator_approved"] is True
    assert record["no_pnl_inference"] is True
    assert record["no_close_attempted"] is True
    assert record["staked_external_position"] is True
    assert record["external_inventory_classification"] == "external_staked_position"
    assert record["tradable_by_bot"] is False
    assert record["manual_close_allowed"] is False
    assert record["bot_inventory"] is False
    assert record["blocks_new_entries"] is False
    assert list((state_root / "state" / "coinbase" / "backups").glob("*.json"))


def test_normalized_state_no_longer_blocks_new_entries(tmp_path):
    state_root = _copy_state(tmp_path, "manual_review_sol_state")
    before_counts = calculate_crypto_entry_blockers(_positions(state_root))
    assert before_counts == (1, 1)

    remediation.build_report(
        state_root=state_root,
        assertion_json=FIXTURES / "external_staked_sol_assertion.json",
        apply=True,
        operator_approved=True,
    )

    after_counts = calculate_crypto_entry_blockers(_positions(state_root))
    assert after_counts == (0, 0)


def test_external_inventory_fields_do_not_block_even_if_left_in_open_positions():
    positions = {
        "SOL/USD": {
            "asset_class": "crypto",
            "user_action_required": True,
            "api_controllable": False,
            "exit_evaluation_enabled": False,
            "staked_external_position": True,
            "external_inventory_classification": "external_staked_position",
            "tradable_by_bot": False,
            "manual_close_allowed": False,
            "bot_inventory": False,
        }
    }

    assert calculate_crypto_entry_blockers(positions) == (0, 0)


def test_true_bot_owned_unresolved_position_still_blocks():
    positions = {
        "BTC/USD": {
            "asset_class": "crypto",
            "user_action_required": True,
            "api_controllable": False,
            "exit_evaluation_enabled": False,
            "bot_opened": True,
        }
    }

    assert calculate_crypto_entry_blockers(positions) == (1, 1)


def test_missing_or_malformed_state_refuses(tmp_path):
    missing = remediation.build_report(state_root=tmp_path)
    assert missing["verdict"] == "NOT_SAFE_TO_NORMALIZE"
    assert "state_file_missing" in missing["refusal_reasons"]

    malformed_root = tmp_path / "bad"
    (malformed_root / "state" / "coinbase").mkdir(parents=True)
    (malformed_root / "state" / "coinbase" / "open_positions.json").write_text("{bad")
    malformed = remediation.build_report(state_root=malformed_root)
    assert malformed["verdict"] == "NOT_SAFE_TO_NORMALIZE"
    assert any(reason.startswith("state_file_malformed") for reason in malformed["refusal_reasons"])


def test_pending_exit_activity_refuses(tmp_path):
    state_root = _copy_state(tmp_path, "manual_review_sol_state")
    state_path = state_root / "state" / "coinbase" / "open_positions.json"
    data = json.loads(state_path.read_text())
    data["positions"]["SOL/USD"]["close_order_id"] = "close-order-should-not-exist"
    state_path.write_text(json.dumps(data))

    report = remediation.build_report(
        state_root=state_root,
        assertion_json=FIXTURES / "external_staked_sol_assertion.json",
    )

    assert report["verdict"] == "NOT_SAFE_TO_NORMALIZE"
    assert "pending_close_or_exit_activity_unreconciled" in report["refusal_reasons"]


def test_script_has_no_forbidden_runtime_hooks():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "broker_coinbase",
        "load_dotenv",
        "os.environ",
        "place_order",
        "cancel_order",
        "close_position",
        "append_coinbase_fill_row",
        "logs/coinbase_fills.csv",
    ]
    for token in forbidden:
        assert token not in text
