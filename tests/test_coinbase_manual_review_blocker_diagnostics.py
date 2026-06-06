"""Tests for the offline P2-029A manual-review blocker diagnostic."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coinbase_manual_review_blocker_diagnostics.py"
FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_manual_review_blocker_diagnostics"

spec = importlib.util.spec_from_file_location("coinbase_manual_review_blocker_diagnostics", SCRIPT)
diagnostics = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diagnostics
spec.loader.exec_module(diagnostics)


def _report(*, ps: bool = True):
    return diagnostics.build_report(
        journal_path=FIXTURE / "journal_coinbase_crypto.csv",
        open_positions_path=FIXTURE / "open_positions.json",
        external_inventory_path=FIXTURE / "external_inventory.json",
        closed_positions_path=FIXTURE / "closed_positions.json",
        ps_text_path=(FIXTURE / "ps.txt") if ps else None,
    )


def test_reports_ada_and_sol_manual_review_blockers():
    report = _report()
    blockers = {(row["symbol"], row["source"]): row for row in report["current_manual_review_blockers"]}

    assert blockers[("ADA/USD", "open_positions")]["manual_review_reason"] == "broker_close_capability_unconfirmed"
    assert blockers[("SOL/USD", "external_inventory")]["manual_review_reason"] == "manual_review_position_open"
    assert blockers[("SOL/USD", "external_inventory")]["bot_inventory"] is False
    assert report["current_manual_review_blocker_symbols"] == ["ADA/USD", "SOL/USD"]


def test_reports_journal_entry_failed_close_reassociation_and_blocks():
    evidence = _report()["journal_evidence"]

    assert evidence["most_recent_ada_entry_or_fill"]["order_id"] == "ada-entry-1"
    assert "failed close attempts" in evidence["ada_failed_close_warning"]["reason"]
    assert "re-associated" in evidence["ada_broker_reassociated_warning"]["reason"]
    assert evidence["recent_entry_blocked_count"] == 2
    assert [row["symbol"] for row in evidence["recent_entry_blocked_rows"]] == ["BTC/USD", "ETH/USD"]


def test_duplicate_process_risk_from_captured_ps_text():
    report = _report()
    assert report["live_process_count"] == 2
    assert report["blocker_classification"]["duplicate_live_process_risk"] is True
    assert report["blocker_classification"]["safe_to_auto_clear"] is False


def test_process_count_not_evaluated_without_captured_input():
    report = _report(ps=False)
    assert report["live_process_count"] == "not evaluated"
    assert report["blocker_classification"]["duplicate_live_process_risk"] == "not evaluated"


def test_all_authorizations_are_false():
    report = _report()
    for key in (
        "implementation_authorized",
        "state_mutation_authorized",
        "manual_review_clear_authorized",
        "live_trading_unblock_authorized",
        "paper_probe_authorized",
        "live_probe_authorized",
        "scaling_authorized",
    ):
        assert report[key] is False


def test_default_build_is_read_only(tmp_path):
    paths = {}
    for name in ("journal_coinbase_crypto.csv", "open_positions.json", "external_inventory.json", "closed_positions.json", "ps.txt"):
        source = FIXTURE / name
        target = tmp_path / name
        target.write_bytes(source.read_bytes())
        paths[name] = target
    before = {name: path.read_bytes() for name, path in paths.items()}

    diagnostics.build_report(
        journal_path=paths["journal_coinbase_crypto.csv"],
        open_positions_path=paths["open_positions.json"],
        external_inventory_path=paths["external_inventory.json"],
        closed_positions_path=paths["closed_positions.json"],
        ps_text_path=paths["ps.txt"],
    )

    assert before == {name: path.read_bytes() for name, path in paths.items()}
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(paths)


def test_cli_json_and_explicit_output(tmp_path, capsys):
    output = tmp_path / "diagnostic.json"
    rc = diagnostics.main(
        [
            "--journal", str(FIXTURE / "journal_coinbase_crypto.csv"),
            "--open-positions", str(FIXTURE / "open_positions.json"),
            "--external-inventory", str(FIXTURE / "external_inventory.json"),
            "--closed-positions", str(FIXTURE / "closed_positions.json"),
            "--ps-text", str(FIXTURE / "ps.txt"),
            "--output", str(output),
            "--json",
        ]
    )

    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text())
    assert printed == written
    assert written["verdict"] == "BLOCKED_MANUAL_REVIEW_POSITION"


def test_script_has_no_actionable_live_hooks():
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = (
        "broker_coinbase",
        "load_dotenv",
        "os.environ",
        "requests.",
        "urllib.",
        "subprocess.",
        "create_" + "order",
        "place_" + "order",
        "cancel_" + "order",
        "close_" + "position",
        "launch" + "ctl",
        "live-read-" + "only",
    )
    for token in forbidden:
        assert token not in source


def test_text_report_is_explicitly_non_authorizing():
    text = diagnostics.render_text(_report())
    assert "verdict=BLOCKED_MANUAL_REVIEW_POSITION" in text
    assert "blocker symbol=ADA/USD source=open_positions" in text
    assert "blocker symbol=SOL/USD source=external_inventory" in text
    assert "manual_review_clear_authorized=false" in text
    assert "scaling_authorized=false" in text
