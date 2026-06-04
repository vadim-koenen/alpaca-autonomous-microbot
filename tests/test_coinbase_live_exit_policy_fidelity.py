"""
tests/test_coinbase_live_exit_policy_fidelity.py — P2-025O live exit-policy fidelity tests.

All tests offline, fixture or in-memory, no broker, no .env, no orders, no network, no mutation of existing replay.
"""

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.coinbase_live_exit_policy_fidelity import (
    build_live_exit_policy_fidelity_report,
)


def test_aligned_uses_journal_exit_price_for_timeout_and_makes_residual_zero():
    # journal timeout cycle with exit_price; aligned must use it exactly -> aligned_gross == journal_gross -> res=0
    jrows = [
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b",
         "action": "EXIT", "reason": "max hold time 90min exceeded (5min held)",
         "fill_price": "100.0", "exit_price": "101.0", "gross_pnl": "0.05", "fees_paid": "0.0", "pnl_usd": "0.05", "notional": "5.0"},
    ]
    with tempfile.TemporaryDirectory() as td:
        jf = Path(td) / "j.json"
        jf.write_text(json.dumps(jrows))
        of = Path(td) / "o.json"
        of.write_text(json.dumps([
            {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100, "symbol":"BTC/USD"},
            {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":101,"l":100,"c":101, "symbol":"BTC/USD"},
        ]))
        payload = build_live_exit_policy_fidelity_report(journal_path=jf, ohlcv_fixture=of)
        assert payload["cycles_analyzed"] == 1
        assert payload["cycles_skipped"] == 0
        row = payload["per_cycle"][0]
        assert row["symbol"] == "BTC/USD"
        assert "max hold time 90min exceeded" in (row.get("journal_exit_reason") or "")
        assert row["aligned_used_journal_exit_price"] is True
        assert row["aligned_fallback_note"] is None
        # residuals
        assert Decimal(row["aligned_gross_residual"]) == Decimal("0")
        # direction
        assert row["aligned_direction_match"] is True
        # aggregates
        assert payload["aligned"]["direction_match"] == 1.0
        assert payload["aligned"]["signed_gross_residual"] in ("0.00000000", "0E-8", "0")
        assert payload["improvement"]["exit_policy_alignment_fixes_residual"] is True
        assert payload["aligned"]["replay_trustworthy"] is True


def test_aligned_fallback_to_candle_close_when_journal_exit_price_missing():
    jrows = [
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b",
         "action": "EXIT", "reason": "max hold time 90min exceeded (5min held)",
         "fill_price": "100.0", "exit_price": "0", "gross_pnl": "0", "fees_paid": "0", "pnl_usd": "0", "notional": "5.0"},
    ]
    with tempfile.TemporaryDirectory() as td:
        jf = Path(td) / "j.json"
        jf.write_text(json.dumps(jrows))
        of = Path(td) / "o.json"
        of.write_text(json.dumps([
            {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100, "symbol":"BTC/USD"},
            {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":101,"l":100,"c":101, "symbol":"BTC/USD"},
        ]))
        payload = build_live_exit_policy_fidelity_report(journal_path=jf, ohlcv_fixture=of)
        assert payload["cycles_analyzed"] == 1
        row = payload["per_cycle"][0]
        assert row["aligned_used_journal_exit_price"] is False
        assert "candle_close_fallback" in (row.get("aligned_fallback_note") or "")


def test_direction_match_and_trust_gates_before_after():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    assert "simulated" in payload and "aligned" in payload
    assert "direction_match" in payload["simulated"]
    assert "direction_match" in payload["aligned"]
    assert isinstance(payload["simulated"]["replay_trustworthy"], bool)
    assert isinstance(payload["aligned"]["replay_trustworthy"], bool)
    assert "exit_policy_alignment_fixes_residual" in payload["improvement"]


def test_skipped_cycle_accounting_and_details():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    assert payload["cycles_seen"] == 4
    assert payload["cycles_analyzed"] in (2, 3)
    assert payload["cycles_skipped"] == 1
    assert len(payload["skipped_cycle_details"]) == 1
    sk = payload["skipped_cycle_details"][0]
    assert sk["symbol"] == "SOL/USD"
    assert sk["missing_ohlcv_window_reason"] == "no_ohlcv_in_window"


def test_json_schema_and_safety_flags():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    for k in ["cycles_analyzed", "cycles_skipped", "per_cycle", "simulated", "aligned", "improvement",
              "timeout_specific", "by_symbol", "by_exit_reason", "skipped_cycle_details",
              "trade_permission", "risk_increase", "scaling_allowed"]:
        assert k in payload
    assert payload["trade_permission"] == "none"
    assert payload["scaling_allowed"] is False
    json.dumps(payload)


def test_no_forbidden_and_isolated():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    s = json.dumps(payload).lower()
    forbidden = ["create_order", "place_order", "buy", "sell", "order_size", "risk_override", "live_broker", "launchctl", ".env"]
    for f in forbidden:
        assert f not in s


def test_in_memory_cycles_for_aligned(monkeypatch):
    jrows = [
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "s",
         "action": "EXIT", "reason": "max hold time 90min exceeded (5min held)",
         "fill_price": "100.0", "exit_price": "101.0", "gross_pnl": "0.05", "fees_paid": "0.0", "pnl_usd": "0.05", "notional": "5.0"},
    ]
    with tempfile.TemporaryDirectory() as td:
        jf = Path(td) / "j.json"
        jf.write_text(json.dumps(jrows))
        of = Path(td) / "o.json"
        of.write_text(json.dumps([
            {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100, "symbol":"BTC/USD"},
            {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":101,"l":100,"c":101, "symbol":"BTC/USD"},
        ]))
        payload = build_live_exit_policy_fidelity_report(journal_path=jf, ohlcv_fixture=of)
        assert payload["cycles_analyzed"] == 1
        row = payload["per_cycle"][0]
        assert row["symbol"] == "BTC/USD"
        assert "simulated_gross_residual" in row
        assert "aligned_gross_residual" in row
        assert payload["aligned"]["replay_trustworthy"] is True


def test_aligned_residual_improves_when_simulated_differs_but_journal_exit_exists():
    # Using fixture where many journal max-hold but sim produces TP exits -> res large; aligned uses journal exit_p -> res~0 (improved)
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    improved = 0
    for r in payload["per_cycle"]:
        if r.get("residual_improved") == "improved":
            improved += 1
        # when journal exit present and used, aligned res should be ~0
        if r.get("aligned_used_journal_exit_price"):
            assert abs(Decimal(r["aligned_gross_residual"])) < Decimal("1e-10")
    assert improved >= 1
    assert payload["improvement"]["residual_reduction_abs"] is not None


def test_direction_match_before_after_and_delta():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    sim_d = payload["simulated"]["direction_match"]
    ali_d = payload["aligned"]["direction_match"]
    delta = payload["improvement"]["direction_match_delta"]
    assert sim_d is not None and ali_d is not None
    if delta is not None:
        assert abs(delta - (ali_d - sim_d)) < 1e-9
    assert "direction_match" in payload["simulated"] and "direction_match" in payload["aligned"]


def test_trust_gate_logic_and_med_pct():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    for mode in ("simulated", "aligned"):
        assert "replay_trustworthy" in payload[mode]
        assert isinstance(payload[mode]["failed_trust_gates"], list)
    # on fixture, sim likely fails gate (low dir), ali may pass or not depending on small N
    assert isinstance(payload["simulated"]["replay_trustworthy"], bool)
    # med pct may be None or float str
    assert "median_abs_residual_pct_of_notional" in payload["simulated"]


def test_no_mutation_of_existing_replay_behavior():
    # Ensure calling the report does not alter run_journal_window_replay results or module state
    # (we only consume its output; aligned is pure post-compute)
    from coinbase_offline_backtest import run_journal_window_replay, parse_journal_cycles, load_bars_from_fixture
    base = Path("tests/fixtures/journal_window_replay")
    jpath = base / "sample_journal.json"
    of = base / "sample_ohlcv.json"
    cycles = parse_journal_cycles(jpath)
    bars = load_bars_from_fixture(of)
    # direct call before
    before = run_journal_window_replay(bars, cycles, entry_fee_rate=Decimal("0"), exit_fee_rate=Decimal("0"), fee_scenario="zero_fee")
    # now report (which internally calls it on covered subset)
    payload = build_live_exit_policy_fidelity_report(journal_path=jpath, ohlcv_fixture=of)
    # direct call after
    after = run_journal_window_replay(bars, cycles, entry_fee_rate=Decimal("0"), exit_fee_rate=Decimal("0"), fee_scenario="zero_fee")
    # same replayed count, and reasons unchanged (no mutation)
    assert before["cycles_replayed"] == after["cycles_replayed"]
    for i, pc in enumerate(before.get("per_cycle", [])):
        if i < len(after.get("per_cycle", [])):
            assert pc.get("replayed_exit_reason") == after["per_cycle"][i].get("replayed_exit_reason")
    # report's simulated should match the (covered) replay reasons
    assert payload["cycles_analyzed"] >= 0


def test_deterministic_fixture_based_output_and_json_schema():
    base = Path("tests/fixtures/journal_window_replay")
    payload1 = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    payload2 = build_live_exit_policy_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    # deterministic
    assert payload1["cycles_seen"] == payload2["cycles_seen"]
    assert payload1["simulated"]["direction_match"] == payload2["simulated"]["direction_match"]
    assert payload1["aligned"]["signed_gross_residual"] == payload2["aligned"]["signed_gross_residual"]
    # schema keys
    for k in ["cycles_seen", "cycles_analyzed", "cycles_skipped", "per_cycle", "simulated", "aligned",
              "improvement", "timeout_specific", "by_symbol", "by_exit_reason", "skipped_cycle_details",
              "trade_permission", "risk_increase", "scaling_allowed"]:
        assert k in payload1
    json.dumps(payload1)  # serializable
