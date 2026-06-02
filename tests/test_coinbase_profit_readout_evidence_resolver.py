# ADVISORY ONLY - tests for P2-021A offline profit readout evidence resolver.
# No broker calls, no .env reads, no order activity, no state/log writes.

from pathlib import Path
import importlib.util
import json
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_profit_readout_evidence_resolver.py"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "coinbase_profit_readout"
ONE_CYCLE_FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "coinbase_read_only_one_cycle_payload"

spec = importlib.util.spec_from_file_location("profit_resolver", SCRIPT)
resolver = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = resolver
spec.loader.exec_module(resolver)


def _report(name: str):
    return resolver.build_report(FIXTURES / name)


def _one_cycle_report(name: str):
    return resolver.build_report(ONE_CYCLE_FIXTURES / name)


def test_complete_direct_entry_exit_evidence_moves_to_measured_limited_readout():
    report = _report("complete_direct_entry_exit_evidence.json")

    assert report["verdict"] == "EVIDENCE_RESOLVED"
    assert report["profit_readout"] == "measured_broker_backed_limited"
    assert report["evidence_level"] == "L4_direct_entry_exit_broker_facts"
    assert report["aggregation_allowed"] is True
    assert report["scaling_allowed"] is False
    assert report["entry_evidence_available"] is True
    assert report["exit_evidence_available"] is True
    assert report["direct_fee_available"] is True
    assert report["direct_proceeds_or_filled_value_available"] is True
    assert report["direct_order_id_available"] is True
    assert report["direct_trade_or_fill_id_available"] is True
    assert report["required_missing_fields"] == []


def test_missing_fee_keeps_profit_readout_unsafe():
    report = _report("missing_fee.json")

    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["aggregation_allowed"] is False
    assert report["scaling_allowed"] is False
    assert report["direct_fee_available"] is False
    assert any(field.endswith(".entry.direct_fee") for field in report["required_missing_fields"])


def test_missing_proceeds_or_filled_value_keeps_profit_readout_unsafe():
    report = _report("missing_proceeds_filled_value.json")

    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["aggregation_allowed"] is False
    assert report["direct_proceeds_or_filled_value_available"] is False
    assert any("direct_proceeds_or_filled_value" in field for field in report["required_missing_fields"])


def test_missing_order_or_fill_id_keeps_profit_readout_unsafe():
    report = _report("missing_order_or_fill_id.json")

    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["aggregation_allowed"] is False
    assert report["direct_order_id_available"] is False
    assert report["direct_trade_or_fill_id_available"] is False
    assert any("direct_order_id" in field for field in report["required_missing_fields"])
    assert any("direct_trade_or_fill_id" in field for field in report["required_missing_fields"])


def test_staked_sol_is_excluded_from_bot_inventory_and_pl():
    report = _report("staked_sol_external_inventory.json")

    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["evidence_level"] == "EXTERNAL_LOCKED_INVENTORY_EXCLUDED"
    assert report["aggregation_allowed"] is False
    assert report["scaling_allowed"] is False
    assert report["staked_external_position"] is True
    assert report["bot_inventory"] is False
    assert any("external/staked" in blocker for blocker in report["blockers"])


def test_local_journal_pnl_never_unlocks_aggregation():
    report = _report("local_journal_only_pnl.json")

    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["aggregation_allowed"] is False
    assert report["scaling_allowed"] is False
    assert report["local_journal_only_pnl"] is True
    assert any("Local journal P/L" in blocker for blocker in report["blockers"])


def test_existing_recent_fills_sample_with_direct_facts_can_be_resolved(tmp_path):
    probe = {
        "broker_read_successful": True,
        "staked_external_position": False,
        "bot_inventory": True,
        "recent_fills_sample": [
            {
                "trade_id": "entry-001",
                "order_id": "entry-order-001",
                "product_id": "SOL-USD",
                "side": "BUY",
                "size": "0.01",
                "price": "80",
                "fee": "0.05",
                "filled_value": "0.80",
            },
            {
                "trade_id": "exit-001",
                "order_id": "exit-order-001",
                "product_id": "SOL-USD",
                "side": "SELL",
                "size": "0.01",
                "price": "82",
                "fee": "0.06",
                "filled_value": "0.82",
            },
        ],
    }
    probe_file = tmp_path / "probe.json"
    probe_file.write_text(json.dumps(probe), encoding="utf-8")
    report = resolver.build_report(probe_file)

    assert report["profit_readout"] == "measured_broker_backed_limited"
    assert report["aggregation_allowed"] is True
    assert report["scaling_allowed"] is False


def test_one_cycle_read_only_payload_resolves_to_limited_broker_backed_readout():
    report = _one_cycle_report("real_ethusd_029_redacted_payload.json")

    assert report["verdict"] == "EVIDENCE_RESOLVED"
    assert report["profit_readout"] == "measured_broker_backed_limited"
    assert report["evidence_level"] == "L4_direct_entry_exit_broker_facts"
    assert report["aggregation_allowed"] is True
    assert report["scaling_allowed"] is False
    assert report["cycles_evaluated"] == 1
    assert report["complete_direct_cycles"] == 1
    assert report["required_missing_fields"] == []
    assert "No direct entry+exit evidence cycles supplied." not in report["blockers"]
    assert report["direct_order_id_available"] is True
    assert report["direct_trade_or_fill_id_available"] is True
    assert report["direct_fee_available"] is True
    assert report["direct_proceeds_or_filled_value_available"] is True
    assert report["safety"]["risk_increase"] == "not_approved"


def test_one_cycle_read_only_payload_cycle_report_has_entry_and_exit_available():
    report = _one_cycle_report("real_ethusd_029_redacted_payload.json")
    cycle = report["cycle_reports"][0]

    assert cycle["cycle_id"] == "real-ethusd-029"
    assert cycle["product_id"] == "ETH-USD"
    assert cycle["complete_direct_evidence"] is True
    assert cycle["entry"]["side"] == "BUY"
    assert cycle["exit"]["side"] == "SELL"
    assert cycle["entry"]["fills_count"] == 1
    assert cycle["exit"]["fills_count"] == 1


def test_resolver_does_not_import_broker_or_reference_production_fill_logger():
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


def test_resolver_is_read_only_and_does_not_read_env(tmp_path, monkeypatch):
    probe_file = FIXTURES / "missing_fee.json"
    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    before = {p.name for p in tmp_path.iterdir()}
    report = resolver.build_report(probe_file)
    after = {p.name for p in tmp_path.iterdir()}

    assert report["safety"]["broker_calls_made"] is False
    assert report["safety"]["live_read_only_used"] is False
    assert report["safety"]["secrets_or_env_read"] is False
    assert report["safety"]["orders_cancels_closes_modifications"] is False
    assert report["safety"]["state_or_log_mutation"] is False
    assert after == before
