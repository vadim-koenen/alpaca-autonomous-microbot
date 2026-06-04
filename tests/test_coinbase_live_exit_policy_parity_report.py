import json
from decimal import Decimal
from pathlib import Path

from scripts.coinbase_live_exit_policy_parity_report import (
    build_live_exit_policy_parity_report,
)


def _write_fixture(tmp_path: Path):
    journal = tmp_path / "journal.json"
    ohlcv = tmp_path / "ohlcv.json"
    journal.write_text(json.dumps([
        {
            "timestamp": "2026-01-01T00:10:00Z",
            "mode": "live",
            "symbol": "BTC/USD",
            "strategy": "fixture",
            "action": "EXIT",
            "reason": "max hold time 10min exceeded (10min held)",
            "fill_price": "100",
            "exit_price": "100.5",
            "gross_pnl": "0.025",
            "fees_paid": "0",
            "pnl_usd": "0.025",
            "notional": "5",
        },
        {
            "timestamp": "2026-01-01T00:30:00Z",
            "mode": "live",
            "symbol": "ETH/USD",
            "strategy": "fixture",
            "action": "EXIT",
            "reason": "take-profit hit @ 103.00 (10min held)",
            "fill_price": "100",
            "exit_price": "103",
            "gross_pnl": "0.15",
            "fees_paid": "0",
            "pnl_usd": "0.15",
            "notional": "5",
        },
        {
            "timestamp": "2026-01-01T00:50:00Z",
            "mode": "live",
            "symbol": "ALGO/USD",
            "strategy": "fixture",
            "action": "EXIT",
            "reason": "stop-loss hit @ 98.50 (10min held)",
            "fill_price": "100",
            "exit_price": "98.5",
            "gross_pnl": "-0.075",
            "fees_paid": "0",
            "pnl_usd": "-0.075",
            "notional": "5",
        },
        {
            "timestamp": "2026-01-01T01:10:00Z",
            "mode": "live",
            "symbol": "SOL/USD",
            "strategy": "fixture",
            "action": "EXIT",
            "reason": "max hold time 10min exceeded (10min held)",
            "fill_price": "100",
            "exit_price": "105",
            "gross_pnl": "0.25",
            "fees_paid": "0",
            "pnl_usd": "0.25",
            "notional": "5",
        },
    ]), encoding="utf-8")
    ohlcv.write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o": 100, "h": 100, "l": 100, "c": 100, "symbol": "BTC/USD"},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o": 100, "h": 101, "l": 99, "c": 100.25, "symbol": "BTC/USD"},
        {"timestamp_utc": "2026-01-01T00:10:00Z", "o": 100.25, "h": 102, "l": 99, "c": 100.5, "symbol": "BTC/USD"},
        {"timestamp_utc": "2026-01-01T00:20:00Z", "o": 100, "h": 100, "l": 100, "c": 100, "symbol": "ETH/USD"},
        {"timestamp_utc": "2026-01-01T00:25:00Z", "o": 100, "h": 104, "l": 99, "c": 101, "symbol": "ETH/USD"},
        {"timestamp_utc": "2026-01-01T00:30:00Z", "o": 101, "h": 104, "l": 100, "c": 103, "symbol": "ETH/USD"},
        {"timestamp_utc": "2026-01-01T00:40:00Z", "o": 100, "h": 100, "l": 100, "c": 100, "symbol": "ALGO/USD"},
        {"timestamp_utc": "2026-01-01T00:45:00Z", "o": 100, "h": 101, "l": 97, "c": 99, "symbol": "ALGO/USD"},
        {"timestamp_utc": "2026-01-01T00:50:00Z", "o": 99, "h": 100, "l": 98, "c": 98.5, "symbol": "ALGO/USD"},
        {"timestamp_utc": "2026-01-01T01:00:00Z", "o": 100, "h": 100, "l": 100, "c": 100, "symbol": "SOL/USD"},
        {"timestamp_utc": "2026-01-01T01:05:00Z", "o": 100, "h": 104, "l": 99, "c": 100.2, "symbol": "SOL/USD"},
        {"timestamp_utc": "2026-01-01T01:10:00Z", "o": 100.2, "h": 104, "l": 99, "c": 100, "symbol": "SOL/USD"},
    ]), encoding="utf-8")
    return journal, ohlcv


def test_report_contains_three_modes_and_control_label(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path)
    payload = build_live_exit_policy_parity_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    assert payload["mode_order"] == [
        "original_simulated_tp_sl_high_low",
        "journal_exit_aligned_control",
        "predictive_live_exit_policy",
    ]
    assert payload["modes"]["journal_exit_aligned_control"]["control_only"] is True
    assert payload["aligned_replay_trustworthy_scope"] == "reconciliation_control_only_not_predictive_backtest_evidence"
    assert payload["aligned_mode_used_for_prediction"] is False
    assert payload["forward_looking_fields_used"] is False


def test_predictive_path_does_not_use_journal_exit_for_prediction(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path)
    payload = build_live_exit_policy_parity_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    predictive = payload["modes"]["predictive_live_exit_policy"]
    assert predictive["used_journal_exit_price_count"] == 0
    assert predictive["used_journal_exit_time_for_prediction_count"] == 0
    assert payload["predictive_replay_trustworthy"] is False


def test_timeout_prediction_uses_close_not_high_low_leakage(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path)
    payload = build_live_exit_policy_parity_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    rows = payload["top_residual_cycles"] + payload["top_mismatch_cycles"]
    sol_rows = [r for r in rows if r["symbol"] == "SOL/USD"]
    if not sol_rows:
        sol_rows = [
            r for r in payload["top_residual_cycles"] + payload["top_mismatch_cycles"]
            if r["cycle_index"] == 3
        ]
    assert payload["modes"]["predictive_live_exit_policy"]["used_high_low_for_timeout_count"] == 0
    assert any(r["basis"] == "scan_candle_close_at_or_after_entry_plus_max_hold" for r in sol_rows)
    assert any(r["mode_exit_reason"].startswith("max hold time") for r in sol_rows)


def test_metrics_and_gate_fields_are_present(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path)
    payload = build_live_exit_policy_parity_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    predictive = payload["modes"]["predictive_live_exit_policy"]
    for key in [
        "direction_match",
        "gross_residual",
        "net_residual_using_journal_fees",
        "median_abs_residual",
        "p90_abs_residual",
        "exit_reason_match_rate",
        "timeout_exit_match_rate",
        "stop_loss_match_rate",
        "take_profit_match_rate",
        "exit_timestamp_delta_median",
        "exit_timestamp_delta_p90",
        "timeout_residual",
        "by_symbol_residual",
        "by_exit_reason_residual",
    ]:
        assert key in predictive
    assert isinstance(payload["failed_predictive_gates"], list)
    assert "predictive_vs_original_residual_delta" in payload["comparisons"]
    assert "predictive_vs_journal_aligned_gap" in payload["comparisons"]


def test_json_schema_and_safety_flags(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path)
    payload = build_live_exit_policy_parity_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    assert payload["trade_permission"] == "none"
    assert payload["scaling_allowed"] is False
    assert payload["risk_increase"] == "not_approved"
    assert payload["original_replay_behavior_modified"] is False
    assert "maker" not in payload["next_required_action"].lower() or "do not implement maker" in payload["next_required_action"].lower()
    json.dumps(payload)


def test_no_forbidden_runtime_language_in_payload(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path)
    payload = build_live_exit_policy_parity_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    text = json.dumps(payload).lower()
    forbidden = [
        "create_order",
        "place_order",
        "cancel_order",
        "close_position",
        "launchctl",
        "--live-read-only",
        ".env",
        "api_key",
    ]
    for phrase in forbidden:
        assert phrase not in text


def test_original_replay_comparator_remains_high_low_sensitive(tmp_path):
    journal, ohlcv = _write_fixture(tmp_path)
    payload = build_live_exit_policy_parity_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    original = payload["modes"]["original_simulated_tp_sl_high_low"]
    predictive = payload["modes"]["predictive_live_exit_policy"]
    assert original["gross_residual"] != predictive["gross_residual"]
    assert Decimal(str(original["gross_residual"])) != Decimal("0")
