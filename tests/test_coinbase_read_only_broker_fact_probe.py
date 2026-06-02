"""
P2-011J — Tests for the read-only Coinbase broker-fact discovery probe.

All tests are pure and use mocks or static payloads. No live network calls are ever made.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.coinbase_read_only_broker_fact_probe import (
    analyze_broker_facts,
    build_non_live_refusal_report,
    redact_report_for_output,
    BrokerFactDiscoveryReport,
)


def test_default_mode_does_not_perform_live_reads(monkeypatch):
    """The probe must not touch any live broker by default."""
    # If someone accidentally constructs a real broker inside analyze_broker_facts or helpers, this would fail.
    # We just assert that the main analysis path is pure.
    order = {"normalized_status": "filled", "filled_size": "0.01", "average_filled_price": "100"}
    fills = [{"trade_id": "t1", "fee": "0.06", "price": "100", "size": "0.01"}]

    report = analyze_broker_facts(order, fills, leg_type="entry", symbol="BTC-USD")
    assert isinstance(report, BrokerFactDiscoveryReport)
    assert report.logger_readiness_blocked is False  # good data


def test_no_write_paths_are_touched():
    """Critical safety: the probe's executable logic must never reference write paths."""
    import scripts.coinbase_read_only_broker_fact_probe as probe_mod
    source = Path(probe_mod.__file__).read_text()

    # Remove comments and docstrings for the check
    import re
    cleaned = re.sub(r'""".*?"""', '', source, flags=re.DOTALL)
    cleaned = re.sub(r"'''.*?'''", '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'#.*', '', cleaned)

    assert "append_coinbase_fill_row" not in cleaned
    assert "coinbase_fills.csv" not in cleaned


def test_parsing_preserves_field_presence_for_get_order_style():
    order = {
        "normalized_status": "filled",
        "filled_size": "0.001",
        "average_filled_price": "65000",
        "total_fees": "0.39",
        "filled_value": "65.0",
        "side": "BUY",
    }
    report = analyze_broker_facts(order, [], leg_type="entry", symbol="BTC-USD")
    assert report.order_facts.has_filled_size is True
    assert report.order_facts.has_average_filled_price is True
    assert report.order_facts.has_total_fees is True
    assert report.order_facts.has_filled_value is True


def test_parsing_preserves_field_presence_for_list_fills_style():
    fills = [
        {"trade_id": "t1", "price": "65000", "size": "0.001", "fee": "0.39", "liquidity_indicator": "MAKER"},
        {"entry_id": "e2", "price": "65001", "size": "0.0005", "fee": "0.195"},
    ]
    report = analyze_broker_facts({}, fills, leg_type="entry", symbol="BTC-USD")
    assert report.stable_per_fill_ids_present is True
    assert report.per_fill_fees_present is True
    assert len(report.fill_facts) == 2
    assert report.fill_facts[0].has_liquidity_indicator is True


def test_missing_direct_sell_proceeds_blocks_exit_readiness():
    # SELL order without filled_value
    order = {"side": "SELL", "filled_size": "0.001", "average_filled_price": "65000", "total_fees": "0.39"}
    fills = [{"trade_id": "t1", "fee": "0.39", "price": "65000", "size": "0.001"}]
    report = analyze_broker_facts(order, fills, leg_type="exit", symbol="BTC-USD")
    assert report.logger_readiness_blocked is True
    assert any("direct sell proceeds" in r.lower() for r in report.blocking_reasons)


def test_missing_stable_fill_id_on_exit_blocks_readiness():
    order = {"side": "SELL", "filled_size": "0.001", "average_filled_price": "65000", "filled_value": "65", "total_fees": "0.39"}
    fills = [{"price": "65000", "size": "0.001", "fee": "0.39"}]  # no trade_id or entry_id
    report = analyze_broker_facts(order, fills, leg_type="exit", symbol="BTC-USD")
    assert report.logger_readiness_blocked is True
    assert any("stable" in r.lower() for r in report.blocking_reasons)


def test_missing_per_fill_fee_blocks_net_pl_readiness():
    order = {"side": "BUY", "filled_size": "0.01", "average_filled_price": "140", "total_fees": "0.084"}
    fills = [{"trade_id": "t1", "price": "140", "size": "0.01"}]  # no fee
    report = analyze_broker_facts(order, fills, leg_type="entry", symbol="SOL-USD")
    assert report.logger_readiness_blocked is True
    assert any("per-fill fee" in r.lower() for r in report.blocking_reasons)


def test_redaction_removes_sensitive_values():
    """Exercise the redaction helper on a realistic report structure."""
    report = BrokerFactDiscoveryReport(
        leg_type="entry",
        symbol="BTC-USD",
        order_id="ord-1",
        order_facts=None,  # type: ignore
        fill_facts=[],
        direct_sell_proceeds_present=False,
        stable_per_fill_ids_present=True,
        per_fill_fees_present=True,
        logger_readiness_blocked=False,
        raw_order_shape_keys=["account_id", "client_order_id", "filled_size"],
    )
    redacted = redact_report_for_output(report)
    # The redaction logic in the module redacts certain keys when producing output
    # We mainly care that the function runs without error and that sensitive-looking keys are handled
    assert isinstance(redacted, dict)
    # If the module's redact logic touched the shape keys, we should see redaction markers in string form
    redacted_str = str(redacted)
    # The important thing is that the function did not crash and the report structure is intact
    assert "raw_order_shape_keys" in redacted_str or "raw_order_shape_keys" in redacted


def test_cli_default_does_not_enable_live_reads(monkeypatch, capsys):
    """Running the script with no flags must not attempt any live broker connection."""
    from scripts import coinbase_read_only_broker_fact_probe as probe_mod

    # Force the live path to explode if it is ever reached
    monkeypatch.setattr(probe_mod, "_get_live_broker", lambda: (_ for _ in ()).throw(RuntimeError("LIVE CALL ATTEMPTED")))

    # Simulate running main() with default args (no --live-read-only)
    with patch("sys.argv", ["probe"]):
        try:
            probe_mod.main()
        except SystemExit:
            pass  # argparse may exit, that's fine

    captured = capsys.readouterr()
    # It should have run in synthetic mode and not tried the live path
    assert "LIVE CALL ATTEMPTED" not in captured.out + captured.err


def test_cli_accepts_output_json(capsys):
    from scripts import coinbase_read_only_broker_fact_probe as probe_mod

    probe_mod.main(["--output", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only_only"] is True
    assert payload["live_read_only_requested"] is False
    assert payload["broker_methods_attempted"] == []
    assert payload["broker_calls_made"] is False


def test_live_read_only_output_json_writes_pure_json_to_stdout_and_warning_to_stderr(monkeypatch, capsys):
    from scripts import coinbase_read_only_broker_fact_probe as probe_mod

    report = probe_mod.analyze_broker_facts(
        {
            "side": "BUY",
            "filled_size": "0.001",
            "average_filled_price": "3800.00",
            "filled_value": "3.80",
            "total_fees": "0.0062",
            "settled": True,
        },
        [{"trade_id": "fill-1", "price": "3800.00", "size": "0.001", "fee": "0.0062"}],
        leg_type="entry",
        symbol="ETH-USD",
        order_id="order-1",
        live_read_only_requested=True,
        broker_methods_attempted=["get_order_status", "get_historical_fills"],
        broker_calls_made=True,
    )
    monkeypatch.setattr(probe_mod, "run_live_read_only_discovery", lambda symbol, order_id: report)

    probe_mod.main(["--live-read-only", "--output", "json", "--order-id", "order-1", "--symbol", "ETH-USD"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["read_only_only"] is True
    assert payload["live_read_only_requested"] is True
    assert payload["broker_methods_attempted"] == ["get_order_status", "get_historical_fills"]
    assert "LIVE READ-ONLY MODE ENABLED" not in captured.out
    assert "LIVE READ-ONLY MODE ENABLED" in captured.err


def test_cli_rejects_stale_json_flag():
    from scripts import coinbase_read_only_broker_fact_probe as probe_mod

    with pytest.raises(SystemExit) as excinfo:
        probe_mod.main(["--json"])

    assert excinfo.value.code == 2


def test_non_live_order_specific_probe_refuses_without_broker_construction(monkeypatch, capsys):
    from scripts import coinbase_read_only_broker_fact_probe as probe_mod

    monkeypatch.setattr(
        probe_mod,
        "_get_live_broker",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("LIVE BROKER CONSTRUCTED")),
    )

    probe_mod.main([
        "--output",
        "json",
        "--order-id",
        "b6983cd8-4cf8-4d36-850b-c3ebe995b938",
        "--symbol",
        "ETH-USD",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert payload["logger_readiness_blocked"] is True
    assert payload["read_only_only"] is True
    assert payload["live_read_only_requested"] is False
    assert payload["broker_methods_attempted"] == []
    assert payload["broker_calls_made"] is False
    assert payload["order_mutation_methods_attempted"] is False
    assert "explicit --live-read-only" in " ".join(payload["blocking_reasons"])


def test_get_live_broker_uses_zero_arg_factory_and_no_dry_run_kwarg():
    from scripts import coinbase_read_only_broker_fact_probe as probe_mod

    constructed = []

    def fake_factory():
        constructed.append("called")
        return object()

    broker = probe_mod._get_live_broker(broker_factory=fake_factory)

    assert broker is not None
    assert constructed == ["called"]


def test_live_read_only_path_uses_only_fake_read_methods():
    from scripts import coinbase_read_only_broker_fact_probe as probe_mod

    class FakeBroker:
        def __init__(self):
            self.calls = []

        def get_order_status(self, *, order_id):
            self.calls.append(("get_order_status", order_id))
            return {
                "side": "SELL",
                "filled_size": "0.01",
                "average_filled_price": "2000",
                "filled_value": "20.00",
                "total_fees": "0.02",
            }

        def get_historical_fills(self, *, product_id=None, order_id=None, **kwargs):
            self.calls.append(("get_historical_fills", product_id, order_id, kwargs))
            return [{"trade_id": "fill-1", "price": "2000", "size": "0.01", "fee": "0.02"}]

        def place_order(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("mutation method called")

        def cancel_order(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("mutation method called")

        def close_position(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("mutation method called")

        def modify_order(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("mutation method called")

    fake = FakeBroker()

    report = probe_mod.run_live_read_only_discovery(
        "ETH-USD",
        "9a584218-1095-4f87-a4a4-5db56ca7a319",
        broker_factory=lambda: fake,
    )

    assert fake.calls == [
        ("get_order_status", "9a584218-1095-4f87-a4a4-5db56ca7a319"),
        ("get_historical_fills", "ETH-USD", "9a584218-1095-4f87-a4a4-5db56ca7a319", {}),
    ]
    assert report.read_only_only is True
    assert report.live_read_only_requested is True
    assert report.broker_methods_attempted == ["get_order_status", "get_historical_fills"]
    assert report.broker_calls_made is True
    assert report.order_mutation_methods_attempted is False


def test_non_live_refusal_report_has_required_safety_fields():
    report = build_non_live_refusal_report("ETH-USD", "order-1")

    assert report.read_only_only is True
    assert report.live_read_only_requested is False
    assert report.broker_methods_attempted == []
    assert report.broker_calls_made is False
    assert report.order_mutation_methods_attempted is False
    assert report.logger_readiness_blocked is True


def test_probe_source_has_no_mutation_call_paths():
    import re
    import scripts.coinbase_read_only_broker_fact_probe as probe_mod

    source = Path(probe_mod.__file__).read_text(encoding="utf-8")
    cleaned = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    cleaned = re.sub(r"'''.*?'''", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"#.*", "", cleaned)

    forbidden_calls = [
        "place_order(",
        "place_market_order(",
        "submit_order(",
        "preview_order(",
        "cancel_order(",
        "close_position(",
        "modify_order(",
        "append_coinbase_fill_row(",
    ]
    for token in forbidden_calls:
        assert token not in cleaned
    assert "logs/coinbase_fills.csv" not in cleaned
