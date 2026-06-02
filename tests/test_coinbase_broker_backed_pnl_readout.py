# ADVISORY ONLY - tests for offline broker-backed numeric P/L readout.
# No broker calls, no .env reads, no order activity, no state/log writes.

from pathlib import Path
import importlib.util
import json
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_broker_backed_pnl_readout.py"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "coinbase_numeric_broker_pnl"

spec = importlib.util.spec_from_file_location("coinbase_broker_backed_pnl_readout", SCRIPT)
readout = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = readout
spec.loader.exec_module(readout)


def _report(name: str):
    return readout.build_report(FIXTURES / name)


def _write_payload(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _numeric_cycle_payload(**overrides):
    entry_order = {
        "order_id": "entry-order-1",
        "product_id": "ETH-USD",
        "side": "BUY",
        "status": "FILLED",
        "settled": True,
        "filled_value": "10.0000",
        "total_fees": "0.0500",
    }
    exit_order = {
        "order_id": "exit-order-1",
        "product_id": "ETH-USD",
        "side": "SELL",
        "status": "FILLED",
        "settled": True,
        "filled_value": "10.1200",
        "total_fees": "0.0500",
    }
    payload = {
        "broker_read_successful": True,
        "bot_inventory": True,
        "evidence_cycles": [
            {
                "cycle_id": "direct-cycle",
                "product_id": "ETH-USD",
                "entry": {
                    "order": entry_order,
                    "fills": [
                        {
                            "trade_id": "entry-fill-1",
                            "order_id": "entry-order-1",
                            "product_id": "ETH-USD",
                            "side": "BUY",
                            "fee": "0.0500",
                            "filled_value": "10.0000",
                        }
                    ],
                },
                "exit": {
                    "order": exit_order,
                    "fills": [
                        {
                            "trade_id": "exit-fill-1",
                            "order_id": "exit-order-1",
                            "product_id": "ETH-USD",
                            "side": "SELL",
                            "fee": "0.0500",
                            "filled_value": "10.1200",
                        }
                    ],
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_computes_gross_and_net_pnl_from_direct_numeric_broker_values():
    report = _report("one_cycle_numeric_payload.json")

    assert report["verdict"] == "MEASURED_BROKER_BACKED_LIMITED"
    assert report["profit_readout"] == "measured_broker_backed_limited"
    assert report["cycles_evaluated"] == 1
    assert report["complete_numeric_cycles"] == 1
    assert report["gross_pnl"] == "0.1200"
    assert report["total_fees"] == "0.1000"
    assert report["net_pnl"] == "0.0200"
    assert report["net_pnl_direction"] == "positive"
    assert report["scaling_allowed"] is False
    assert report["risk_increase"] == "not_approved"


def test_blocks_when_values_are_redacted_presence_markers():
    report = _report("one_cycle_redacted_presence_only_payload.json")

    assert report["verdict"] == "BLOCKED"
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["resolver_verdict"] == "EVIDENCE_RESOLVED"
    assert report["numeric_values_redacted"] is True
    assert report["gross_pnl"] is None
    assert report["net_pnl"] is None
    assert any("redacted presence markers" in blocker for blocker in report["blockers"])
    assert report["scaling_allowed"] is False


def test_blocks_when_entry_or_exit_missing(tmp_path):
    payload = _numeric_cycle_payload()
    payload["evidence_cycles"][0]["exit"] = {}
    report = readout.build_report(_write_payload(tmp_path, payload))

    assert report["verdict"] == "BLOCKED"
    assert report["complete_numeric_cycles"] == 0
    assert any("exit." in field for field in report["cycle_reports"][0]["missing_fields"])


def test_blocks_when_fees_missing(tmp_path):
    payload = _numeric_cycle_payload()
    payload["evidence_cycles"][0]["entry"]["order"].pop("total_fees")
    payload["evidence_cycles"][0]["entry"]["fills"][0].pop("fee")
    report = readout.build_report(_write_payload(tmp_path, payload))

    assert report["verdict"] == "BLOCKED"
    assert report["gross_pnl"] is None
    assert any("entry.numeric_total_fees" in field for field in report["cycle_reports"][0]["missing_fields"])


def test_treats_exit_filled_value_as_proceeds_equivalent():
    report = _report("one_cycle_numeric_payload.json")
    cycle = report["cycle_reports"][0]

    assert cycle["exit"]["filled_value_or_proceeds"] == "10.1200"
    assert cycle["gross_pnl"] == "0.1200"


def test_does_not_use_local_journal_pnl(tmp_path):
    payload = _numeric_cycle_payload(
        local_journal_only_pnl=True,
        journal_rows=[{"symbol": "ETH/USD", "net_pnl": "999.00"}],
    )
    report = readout.build_report(_write_payload(tmp_path, payload))

    assert report["verdict"] == "BLOCKED"
    assert report["local_journal_only_pnl"] is True
    assert report["gross_pnl"] is None
    assert any("Local journal P/L" in blocker for blocker in report["blockers"])


def test_redacts_identifiers_by_default_and_can_show_when_disabled():
    redacted = _report("one_cycle_numeric_payload.json")
    unredacted = readout.build_report(
        FIXTURES / "one_cycle_numeric_payload.json",
        redact_identifiers=False,
    )

    assert redacted["cycle_reports"][0]["entry"]["order_ids"] == ["<REDACTED_ORDER_ID>"]
    assert redacted["cycle_reports"][0]["entry"]["fill_ids"] == ["<REDACTED_FILL_ID>"]
    assert unredacted["cycle_reports"][0]["entry"]["order_ids"] == ["entry-order-numeric-001"]
    assert unredacted["cycle_reports"][0]["entry"]["fill_ids"] == ["entry-fill-numeric-001"]


def test_script_is_offline_and_has_no_forbidden_runtime_hooks(tmp_path, monkeypatch):
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "broker_coinbase",
        "load_dotenv",
        "os.environ",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
        "place_order",
        "place_market_order",
        "submit_order",
        "preview_order",
        "cancel_order",
        "close_position",
        "modify_order",
        "max_trade_notional",
        "max_total_crypto_exposure",
        "allow_live_trading_symbols",
    ]
    for token in forbidden:
        assert token not in text

    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}
    report = readout.build_report(FIXTURES / "one_cycle_numeric_payload.json")
    after = {p.name for p in tmp_path.iterdir()}

    assert report["safety"]["offline_only"] is True
    assert report["safety"]["broker_calls_made"] is False
    assert report["safety"]["live_read_only_used"] is False
    assert report["safety"]["secrets_or_env_read"] is False
    assert report["safety"]["orders_cancels_closes_modifications"] is False
    assert report["safety"]["state_or_log_mutation"] is False
    assert report["safety"]["fill_logger_activation"] is False
    assert after == before
