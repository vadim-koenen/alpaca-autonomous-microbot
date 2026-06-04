import json
from decimal import Decimal
from pathlib import Path

from scripts.coinbase_maker_post_only_feasibility_report import (
    _apply_adverse_selection_haircut,
    _apply_non_fill_haircut,
    _compute_fees_and_net,
    build_maker_post_only_feasibility_report,
)


def _write_fixture(tmp_path: Path, *, exit_price: str, cycles: int = 50):
    journal = tmp_path / "journal.json"
    ohlcv = tmp_path / "ohlcv.json"
    journal_rows = []
    bar_rows = []
    for idx in range(cycles):
        hour = idx * 2
        entry_ts = f"2026-01-{1 + (hour // 24):02d}T{hour % 24:02d}:00:00Z"
        mid_ts = f"2026-01-{1 + (hour // 24):02d}T{hour % 24:02d}:05:00Z"
        exit_ts = f"2026-01-{1 + (hour // 24):02d}T{hour % 24:02d}:10:00Z"
        symbol = "BTC/USD" if idx % 2 == 0 else "ETH/USD"
        gross = (Decimal(exit_price) - Decimal("100")) * (Decimal("5") / Decimal("100"))
        journal_rows.append(
            {
                "timestamp": exit_ts,
                "mode": "live",
                "symbol": symbol,
                "strategy": "fixture_momentum" if idx % 2 == 0 else "fixture_reversion",
                "action": "EXIT",
                "reason": "max hold time 10min exceeded (10min held)",
                "fill_price": "100",
                "exit_price": exit_price,
                "gross_pnl": str(gross),
                "fees_paid": "0.12",
                "pnl_usd": str(gross - Decimal("0.12")),
                "notional": "5",
            }
        )
        for ts, close in [(entry_ts, "100"), (mid_ts, "100.5"), (exit_ts, exit_price)]:
            bar_rows.append(
                {
                    "timestamp_utc": ts,
                    "o": "100",
                    "h": close,
                    "l": "99",
                    "c": close,
                    "symbol": symbol,
                }
            )
    journal.write_text(json.dumps(journal_rows), encoding="utf-8")
    ohlcv.write_text(json.dumps(bar_rows), encoding="utf-8")
    return journal, ohlcv


def test_fee_scenario_math():
    fees, net = _compute_fees_and_net(Decimal("0.10"), Decimal("5"), Decimal("0.012"), Decimal("0.012"))
    assert fees == Decimal("0.12120")
    assert net == Decimal("-0.02120")


def test_maker_maker_beats_taker_taker_on_same_fixture(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path, exit_price="102")
    payload = build_maker_post_only_feasibility_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    maker = Decimal(payload["fee_scenarios"]["maker/maker"]["net_pnl_sum"])
    taker = Decimal(payload["fee_scenarios"]["taker/taker"]["net_pnl_sum"])
    zero = Decimal(payload["fee_scenarios"]["zero_fee_theoretical"]["net_pnl_sum"])
    assert zero > maker > taker


def test_adverse_selection_and_non_fill_math_are_conservative():
    assert _apply_adverse_selection_haircut(Decimal("1.00"), Decimal("0.30")) == Decimal("0.7000")
    assert _apply_adverse_selection_haircut(Decimal("-1.00"), Decimal("0.30")) == Decimal("-1.00")
    assert _apply_non_fill_haircut(Decimal("1.00"), Decimal("0.30")) == Decimal("0.7000")
    assert _apply_non_fill_haircut(Decimal("-1.00"), Decimal("0.30")) == Decimal("-1.00")


def test_feasibility_gate_false_when_30pct_haircut_fails(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path, exit_price="101")
    payload = build_maker_post_only_feasibility_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    assert payload["maker_feasible_offline"] is False
    assert any("30pct" in gate for gate in payload["failed_feasibility_gates"])


def test_feasibility_gate_true_when_all_conditions_pass(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path, exit_price="102")
    payload = build_maker_post_only_feasibility_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    assert payload["predictive_replay_baseline"]["predictive_replay_trustworthy"] is True
    assert payload["cycles_analyzed"] == 50
    assert payload["cycles_skipped"] == 0
    assert payload["maker_feasible_offline"] is True
    assert payload["failed_feasibility_gates"] == []


def test_json_schema_and_authorization_flags(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path, exit_price="102")
    payload = build_maker_post_only_feasibility_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    for key in [
        "fee_scenarios",
        "non_fill_adverse_selection_table",
        "notional_sensitivity",
        "fee_break_even_threshold",
        "per_symbol",
        "per_strategy",
        "per_exit_reason",
        "maker_feasible_offline",
        "failed_feasibility_gates",
    ]:
        assert key in payload
    for scenario in [
        "journal_recorded_fees",
        "taker/taker",
        "maker/maker",
        "maker_entry_taker_exit",
        "taker_entry_maker_exit",
        "zero_fee_theoretical",
    ]:
        assert scenario in payload["fee_scenarios"]
    for target in ["$0.50", "$1", "$5", "$10"]:
        assert target in payload["notional_sensitivity"]
    assert payload["implementation_authorized"] is False
    assert payload["paper_probe_authorized"] is False
    assert payload["live_probe_authorized"] is False
    assert payload["scaling_authorized"] is False
    assert payload["trade_permission"] == "none"
    json.dumps(payload)


def test_no_network_auth_live_access_language_in_payload(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path, exit_price="102")
    payload = build_maker_post_only_feasibility_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    text = json.dumps(payload).lower()
    for phrase in [
        "create_order",
        "place_order",
        "cancel_order",
        "close_position",
        "launchctl",
        "live-read-only",
        ".env",
        "authorization",
        "bearer",
        "cb-access",
        "api_key",
        "jwt",
    ]:
        assert phrase not in text


def test_build_does_not_mutate_live_config(tmp_path):
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    journal, ohlcv = _write_fixture(tmp_path, exit_price="102")
    build_maker_post_only_feasibility_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    after = config_path.read_text(encoding="utf-8")
    assert after == before


def test_report_script_contains_no_order_or_broker_implementation():
    source = Path("scripts/coinbase_maker_post_only_feasibility_report.py").read_text(encoding="utf-8")
    for phrase in [
        "create_order",
        "place_order",
        "cancel_order",
        "close_position",
        "append_coinbase_fill_row",
        "coinbase_fills.csv",
    ]:
        assert phrase not in source
