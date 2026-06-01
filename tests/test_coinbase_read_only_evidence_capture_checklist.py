# ADVISORY ONLY - P2-021C offline read-only evidence capture checklist tests.
# No broker calls, no .env reads, no order activity, no state/log writes.

from pathlib import Path
import importlib.util
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_read_only_evidence_capture_checklist.py"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "coinbase_read_only_evidence_capture"

spec = importlib.util.spec_from_file_location("coinbase_read_only_evidence_capture_checklist", SCRIPT)
checklist = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checklist
spec.loader.exec_module(checklist)


def _request(name: str):
    return checklist._safe_load_json(FIXTURES / name)


def test_refuses_ready_without_explicit_human_approval_flag():
    report = checklist.build_checklist_report(
        _request("complete_capture_request.json"),
        human_approved=False,
        source_path="fixture",
    )

    assert report["verdict"] == "BLOCKED"
    assert report["approval_required"] is True
    assert "explicit_human_approval_flag" in report["missing_requirements"]
    assert report["profit_readout_real_current"] == "unsafe_to_aggregate"
    assert report["aggregation_allowed_real_current"] is False
    assert report["scaling_allowed"] is False


def test_complete_request_with_approval_is_ready_for_human_approved_capture_only():
    report = checklist.build_checklist_report(
        _request("complete_capture_request.json"),
        human_approved=True,
        source_path="fixture",
    )

    assert report["verdict"] == "READY_FOR_HUMAN_APPROVED_READ_ONLY_CAPTURE"
    assert report["missing_requirements"] == []
    assert "order_id" in report["required_fields"]
    assert "fee_or_commission" in report["required_fields"]
    assert "filled_value_or_proceeds" in report["required_fields"]
    assert report["expected_adapter_input_file_path"] == "/tmp/coinbase_read_only_evidence_capture_payload.json"
    assert "coinbase_broker_evidence_adapter.py" in report["expected_adapter_command"]
    assert "coinbase_profit_readout_evidence_resolver.py" in report["expected_resolver_command"]


def test_missing_order_ids_product_ids_or_windows_stay_blocked_even_with_approval():
    report = checklist.build_checklist_report(
        _request("missing_identifiers_request.json"),
        human_approved=True,
        source_path="fixture",
    )

    assert report["verdict"] == "BLOCKED"
    assert "incomplete-cycle.product_id" in report["missing_requirements"]
    assert "incomplete-cycle.order_ids.entry" in report["missing_requirements"]
    assert "incomplete-cycle.date_window.end" in report["missing_requirements"]


def test_future_commands_are_output_but_marked_do_not_run_without_approval():
    report = checklist.build_checklist_report(
        _request("complete_capture_request.json"),
        human_approved=True,
        source_path="fixture",
    )

    method_calls = "\n".join(report["planned_future_method_calls"])
    shell_commands = "\n".join(report["planned_future_shell_commands"])
    assert "BrokerCoinbase.get_order_status" in method_calls
    assert "BrokerCoinbase.get_historical_fills" in method_calls
    assert method_calls.count("DO NOT RUN WITHOUT APPROVAL") == 4
    assert "DO NOT RUN WITHOUT APPROVAL" in shell_commands
    assert "coinbase_read_only_broker_fact_probe.py" in shell_commands
    assert "manual_coinbase_read_only_capture.py" not in shell_commands
    assert "--live-read-only" in shell_commands
    assert "--live-read-only --json" in shell_commands


def test_checklist_is_offline_and_has_no_forbidden_runtime_hooks(tmp_path, monkeypatch):
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "import broker_coinbase",
        "from broker_coinbase",
        "load_dotenv",
        "os.environ",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
        "place_order",
        "cancel_order",
        "close_position",
    ]
    for token in forbidden:
        assert token not in text

    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}
    report = checklist.build_checklist_report(
        _request("complete_capture_request.json"),
        human_approved=True,
        source_path="fixture",
    )
    after = {p.name for p in tmp_path.iterdir()}

    assert report["safety"]["offline_only"] is True
    assert report["safety"]["broker_calls_made"] is False
    assert report["safety"]["live_read_only_executed"] is False
    assert report["safety"]["secrets_or_env_read"] is False
    assert report["safety"]["orders_cancels_closes_modifications"] is False
    assert report["safety"]["state_or_log_mutation"] is False
    assert report["safety"]["logs_coinbase_fills_written"] is False
    assert report["safety"]["fill_logger_append_activation"] is False
    assert after == before
