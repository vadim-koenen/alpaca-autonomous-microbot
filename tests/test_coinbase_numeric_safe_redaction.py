# ADVISORY ONLY - tests for offline numeric-safe Coinbase payload redaction.
# No broker calls, no .env reads, no order activity, no state/log writes.

from pathlib import Path
import importlib.util
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "coinbase_numeric_safe_redaction"
REDACTOR_SCRIPT = ROOT / "scripts" / "redact_broker_payload.py"
BUILDER_SCRIPT = ROOT / "scripts" / "coinbase_one_cycle_numeric_safe_payload_builder.py"
READOUT_SCRIPT = ROOT / "scripts" / "coinbase_broker_backed_pnl_readout.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


redactor = _load_module("numeric_safe_redactor", REDACTOR_SCRIPT)
builder = _load_module("numeric_safe_builder", BUILDER_SCRIPT)
readout = _load_module("numeric_safe_readout", READOUT_SCRIPT)


def _fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _assert_raw_identifiers_absent(payload: dict) -> None:
    text = json.dumps(payload, sort_keys=True)
    forbidden_values = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "client-entry-should-redact",
        "client-exit-should-redact",
        "entry-trade-id-000000000001",
        "exit-trade-id-000000000001",
        "entry-entry-id-000000000001",
        "exit-entry-id-000000000001",
        "portfolio-entry-should-redact",
        "portfolio-exit-should-redact",
        "acct-entry-should-redact",
        "acct-exit-should-redact",
        "fake-entry-token",
        "fake-exit-api-key",
        "fake-exit-signature",
    ]
    for value in forbidden_values:
        assert value not in text


def test_numeric_safe_redaction_preserves_order_numeric_pnl_fields_and_redacts_ids():
    raw = _fixture_json("raw_entry_broker_payload.json")
    redacted = redactor.redact_payload(raw, preserve_numeric_pnl_fields=True)

    order = redacted["order_status"]
    assert order["filled_value"] == "10.0000"
    assert order["total_fees"] == "0.0500"
    assert order["filled_size"] == "0.0010"
    assert order["average_filled_price"] == "10000.00"
    assert redacted["order_id"] == "<REDACTED_ORDER_ID>"
    assert order["client_order_id"] == "<REDACTED_CLIENT_ORDER_ID>"
    assert order["retail_portfolio_id"] == "<REDACTED_PORTFOLIO_ID>"
    assert redacted["account_id"] == "<REDACTED_ACCOUNT_ID>"
    assert redacted["authorization"] == "<REDACTED_SECRET>"
    assert redacted["secret_note"] == "<REDACTED_SECRET>"
    assert redacted["fill_facts"][0]["has_stable_id"] is True
    assert redacted["fill_facts"][0]["stable_id_value"] == "<REDACTED_FILL_ID>"
    _assert_raw_identifiers_absent(redacted)


def test_numeric_safe_redaction_preserves_per_fill_fee_price_size():
    raw = _fixture_json("raw_exit_broker_payload.json")
    redacted = redactor.redact_payload(raw, preserve_numeric_pnl_fields=True)
    fill = redacted["fills"][0]

    assert fill["commission"] == "0.0500"
    assert fill["commission_detail_total"] == "0.0500"
    assert fill["price"] == "10120.00"
    assert fill["size"] == "0.0010"
    assert fill["size_in_quote"] == "10.1200"
    assert fill["order_id"] == "<REDACTED_ORDER_ID>"
    assert fill["trade_id"] == "<REDACTED_TRADE_ID>"
    assert fill["entry_id"] == "<REDACTED_ENTRY_ID>"
    assert redacted["api_key"] == "<REDACTED_SECRET>"
    assert redacted["signature"] == "<REDACTED_SECRET>"


def test_legacy_redaction_default_still_uses_existing_behavior():
    raw = {"trade_id": "abc123", "order_id": "a-very-long-order-identifier-that-should-be-truncated"}
    redacted = redactor.redact(raw)

    assert redacted["trade_id"] == "abc123"
    assert redacted["order_id"].startswith("...")


def test_redactor_loader_tolerates_read_only_warning_banner_before_json():
    banner = "!!! LIVE READ-ONLY MODE ENABLED !!!\nNo writes or order actions will be performed.\n"
    raw = redactor._load_json_text(
        banner + (FIXTURES / "raw_entry_broker_payload.json").read_text(encoding="utf-8"),
    )
    redacted = redactor.redact_payload(raw, preserve_numeric_pnl_fields=True)

    assert redacted["order_status"]["filled_value"] == "10.0000"
    assert redacted["fill_facts"][0]["has_stable_id"] is True
    assert redacted["fill_facts"][0]["stable_id_value"] == "<REDACTED_FILL_ID>"


def test_builder_outputs_numeric_safe_one_cycle_schema_and_redacted_identifiers():
    payload = builder.build_one_cycle_payload(
        entry_raw_path=FIXTURES / "raw_entry_broker_payload.json",
        exit_raw_path=FIXTURES / "raw_exit_broker_payload.json",
        cycle_id="numeric-safe-ethusd-001",
        product_id="ETH-USD",
        entry_order_id="11111111-1111-4111-8111-111111111111",
        exit_order_id="22222222-2222-4222-8222-222222222222",
        preserve_numeric_pnl_fields=True,
    )

    expected = _fixture_json("expected_one_cycle_numeric_safe_output.json")
    assert payload["schema_version"] == expected["schema_version"]
    assert payload["capture_scope"] == expected["capture_scope"]
    assert payload["builder_safety"] == expected["builder_safety"]
    cycle = payload["cycles"][0]
    assert cycle["entry_order_id"] == "<REDACTED_ENTRY_ORDER_ID>"
    assert cycle["exit_order_id"] == "<REDACTED_EXIT_ORDER_ID>"
    assert cycle["entry_broker_payload_redacted"]["order_status"]["filled_value"] == "10.0000"
    assert cycle["exit_broker_payload_redacted"]["order_status"]["proceeds"] == "10.1200"
    _assert_raw_identifiers_absent(payload)


def test_numeric_safe_one_cycle_payload_unlocks_limited_numeric_readout(tmp_path):
    output = tmp_path / "numeric_safe_one_cycle.json"
    result = builder.main([
        "--entry-raw",
        str(FIXTURES / "raw_entry_broker_payload.json"),
        "--exit-raw",
        str(FIXTURES / "raw_exit_broker_payload.json"),
        "--output",
        str(output),
        "--cycle-id",
        "numeric-safe-ethusd-001",
        "--product-id",
        "ETH-USD",
        "--entry-order-id",
        "11111111-1111-4111-8111-111111111111",
        "--exit-order-id",
        "22222222-2222-4222-8222-222222222222",
        "--preserve-numeric-pnl-fields",
        "--json",
    ])
    assert result == 0

    report = readout.build_report(output)
    assert report["verdict"] == "MEASURED_BROKER_BACKED_LIMITED"
    assert report["profit_readout"] == "measured_broker_backed_limited"
    assert report["gross_pnl"] == "0.1200"
    assert report["total_fees"] == "0.1000"
    assert report["net_pnl"] == "0.0200"
    assert report["net_pnl_direction"] == "positive"
    assert report["numeric_values_redacted"] is False
    assert report["scaling_allowed"] is False
    assert report["risk_increase"] == "not_approved"


def test_builder_tolerates_read_only_warning_banner_before_json(tmp_path):
    entry = tmp_path / "entry_with_banner.json"
    exit_ = tmp_path / "exit_with_banner.json"
    banner = "!!! LIVE READ-ONLY MODE ENABLED !!!\nNo writes or order actions will be performed.\n"
    entry.write_text(
        banner + (FIXTURES / "raw_entry_broker_payload.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    exit_.write_text(
        banner + (FIXTURES / "raw_exit_broker_payload.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    payload = builder.build_one_cycle_payload(
        entry_raw_path=entry,
        exit_raw_path=exit_,
        cycle_id="numeric-safe-ethusd-001",
        product_id="ETH-USD",
        entry_order_id="11111111-1111-4111-8111-111111111111",
        exit_order_id="22222222-2222-4222-8222-222222222222",
        preserve_numeric_pnl_fields=True,
    )

    assert "_load_error" not in payload["cycles"][0]["entry_broker_payload_redacted"]
    assert "_load_error" not in payload["cycles"][0]["exit_broker_payload_redacted"]
    assert payload["cycles"][0]["entry_broker_payload_redacted"]["order_status"]["filled_value"] == "10.0000"


def test_numeric_safe_scripts_are_offline_and_have_no_forbidden_runtime_hooks(tmp_path, monkeypatch):
    combined_text = "\n".join([
        REDACTOR_SCRIPT.read_text(encoding="utf-8"),
        BUILDER_SCRIPT.read_text(encoding="utf-8"),
    ])
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
        "--live-read-only",
    ]
    for token in forbidden:
        assert token not in combined_text

    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}
    output = tmp_path / "payload.json"
    builder.main([
        "--entry-raw",
        str(FIXTURES / "raw_entry_broker_payload.json"),
        "--exit-raw",
        str(FIXTURES / "raw_exit_broker_payload.json"),
        "--output",
        str(output),
        "--cycle-id",
        "numeric-safe-ethusd-001",
        "--product-id",
        "ETH-USD",
        "--entry-order-id",
        "11111111-1111-4111-8111-111111111111",
        "--exit-order-id",
        "22222222-2222-4222-8222-222222222222",
        "--preserve-numeric-pnl-fields",
    ])
    after = {p.name for p in tmp_path.iterdir()}

    assert after == before | {"payload.json"}
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["builder_safety"]["offline_only"] is True
    assert payload["builder_safety"]["broker_calls_made"] is False
    assert payload["builder_safety"]["live_read_only_used"] is False
    assert payload["builder_safety"]["secrets_or_env_read"] is False
    assert payload["builder_safety"]["orders_cancels_closes_modifications"] is False
    assert payload["builder_safety"]["fill_logger_activation"] is False
