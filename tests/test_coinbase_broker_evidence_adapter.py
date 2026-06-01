# ADVISORY ONLY - P2-021B offline broker evidence adapter tests.
# No broker calls, no .env reads, no order activity, no state/log writes.

from pathlib import Path
import importlib.util
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_broker_evidence_adapter.py"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "coinbase_broker_evidence"

spec = importlib.util.spec_from_file_location("broker_evidence_adapter", SCRIPT)
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


def _report(name: str):
    return adapter.build_adapter_report(FIXTURES / name)


def test_commission_payload_normalizes_to_measured_broker_backed_limited():
    report = _report("complete_commission_payload.json")

    assert report["profit_readout"] == "measured_broker_backed_limited"
    assert report["aggregation_allowed"] is True
    assert report["scaling_allowed"] is False
    resolver = report["resolver_report"]
    assert resolver["direct_fee_available"] is True
    assert resolver["direct_proceeds_or_filled_value_available"] is True
    assert resolver["direct_order_id_available"] is True
    assert resolver["direct_trade_or_fill_id_available"] is True
    entry_fill = report["adapted_evidence"]["evidence_cycles"][0]["entry"]["fills"][0]
    assert entry_fill["fee"] == "0.39"
    assert report["source_map"]["list_fills_or_historical_fills"]["source_keys"] == ["list_fills"]


def test_proceeds_payload_normalizes_to_filled_value_and_unlocks_limited_readout():
    report = _report("complete_proceeds_payload.json")

    assert report["profit_readout"] == "measured_broker_backed_limited"
    assert report["aggregation_allowed"] is True
    exit_order = report["adapted_evidence"]["evidence_cycles"][0]["exit"]["order"]
    exit_fill = report["adapted_evidence"]["evidence_cycles"][0]["exit"]["fills"][0]
    assert exit_order["filled_value"] == "31.40"
    assert exit_order["total_fees"] == "0.20"
    assert exit_fill["filled_value"] == "31.40"


def test_local_journal_estimate_only_remains_unsafe():
    report = _report("local_journal_estimate_only_unsafe.json")

    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["aggregation_allowed"] is False
    assert report["resolver_report"]["local_journal_only_pnl"] is True
    assert report["source_map"]["local_journals"]["sufficient_for_profit_readout"] is False


def test_missing_order_or_fill_id_remains_unsafe():
    report = _report("missing_order_fill_id_unsafe.json")

    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["aggregation_allowed"] is False
    missing = report["resolver_report"]["required_missing_fields"]
    assert any("direct_order_id" in field for field in missing)
    assert any("direct_trade_or_fill_id" in field for field in missing)


def test_adapter_is_offline_and_has_no_forbidden_runtime_hooks(tmp_path, monkeypatch):
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "broker_coinbase",
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
    report = _report("complete_commission_payload.json")
    after = {p.name for p in tmp_path.iterdir()}

    assert report["safety"]["offline_only"] is True
    assert report["safety"]["broker_calls_made"] is False
    assert report["safety"]["live_read_only_used"] is False
    assert report["safety"]["secrets_or_env_read"] is False
    assert report["safety"]["orders_cancels_closes_modifications"] is False
    assert report["safety"]["state_or_log_mutation"] is False
    assert after == before
