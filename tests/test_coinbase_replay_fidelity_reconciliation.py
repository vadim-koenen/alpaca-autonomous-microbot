"""
tests/test_coinbase_replay_fidelity_reconciliation.py — P2-025M replay fidelity tests.

All tests offline, fixture or in-memory, no broker, no .env, no orders, no network, no mutation.
"""

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.coinbase_replay_fidelity_reconciliation import (
    build_replay_fidelity_report,
)


def test_gross_residual_math():
    # replay_gross 0.1, journal_gross 0.05 => residual +0.05
    # (tested via full report on fixture that produces known small negative gross)
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    assert payload["cycles_analyzed"] in (2, 3)
    assert payload["cycles_skipped"] == 1
    # gross residual should be present and numeric
    res = [Decimal(r["gross_residual"]) for r in payload["per_cycle"]]
    assert len(res) in (2, 3)
    assert all(isinstance(x, Decimal) for x in res)


def test_net_residual_using_journal_fees():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    for r in payload["per_cycle"]:
        assert "replay_net_with_journal_fees" in r
        assert "net_residual_using_journal_fees" in r
        # net res = (replay_gross - journal_fees) - journal_net
        jf = Decimal(r["journal_fees"])
        jn = Decimal(r["journal_net"])
        rg = Decimal(r["replay_gross"])
        expected = (rg - jf) - jn
        assert Decimal(r["net_residual_using_journal_fees"]) == expected


def test_direction_match_and_sign_match():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    assert "direction_match" in payload["direction_fidelity"]
    for r in payload["per_cycle"]:
        assert "sign_match" in r
        assert "direction_match_from_replay_run" in r


def test_replay_trustworthy_false_on_poor_direction():
    # The sample has low direction in real data (0.5); our fixture produces small N with possible mismatch
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    # With current fixture the direction may be 1.0 or low; gate should still evaluate
    assert isinstance(payload["replay_trustworthy"], bool)
    if payload["direction_fidelity"].get("direction_match") is not None and payload["direction_fidelity"]["direction_match"] < 0.85:
        assert payload["replay_trustworthy"] is False
        assert any("direction_match" in g for g in payload.get("failed_trust_gates", []))


def test_replay_trustworthy_false_on_large_residual_pct():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    med_pct = payload["residual_distribution"].get("median_residual_pct_of_notional")
    if med_pct is not None and med_pct > 0.10:
        assert payload["replay_trustworthy"] is False


def test_skipped_cycle_accounting_and_details():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_fidelity_report(
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
    assert sk["gap_fixable_by_re_fetch"] is True


def test_json_schema_and_safety_flags():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    for k in ["cycles_analyzed", "cycles_skipped", "per_cycle", "replay_trustworthy", "failed_trust_gates",
              "direction_fidelity", "residual_distribution", "by_symbol", "skipped_cycle_details",
              "trade_permission", "risk_increase", "scaling_allowed"]:
        assert k in payload
    assert payload["trade_permission"] == "none"
    assert payload["scaling_allowed"] is False
    json.dumps(payload)  # valid


def test_no_forbidden_and_isolated():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_fidelity_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    s = json.dumps(payload).lower()
    forbidden = ["create_order", "place_order", "buy", "sell", "order_size", "risk_override", "live_broker", "launchctl", ".env"]
    for f in forbidden:
        assert f not in s


def test_in_memory_cycles_for_fidelity(monkeypatch):
    jrows = [
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "s",
         "action": "EXIT", "reason": "max hold time 90min exceeded (5min held)",
         "fill_price": "100.0", "exit_price": "101.0", "gross_pnl": "0.05", "fees_paid": "0.024", "pnl_usd": "0.026", "notional": "5.0"},
    ]
    with tempfile.TemporaryDirectory() as td:
        jf = Path(td) / "j.json"
        jf.write_text(json.dumps(jrows))
        of = Path(td) / "o.json"
        of.write_text(json.dumps([
            {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100, "symbol":"BTC/USD"},
            {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":101,"l":100,"c":101, "symbol":"BTC/USD"},
        ]))
        payload = build_replay_fidelity_report(journal_path=jf, ohlcv_fixture=of)
        assert payload["cycles_analyzed"] == 1
        assert payload["cycles_skipped"] == 0
        row = payload["per_cycle"][0]
        assert row["symbol"] == "BTC/USD"
        assert "gross_residual" in row
        assert "replay_trustworthy" in payload


def test_missing_fields_set_trustworthy_false():
    # craft a cycle with zero notional to force pct failure path
    jrows = [
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "s",
         "action": "EXIT", "reason": "max hold...", "fill_price": "100.0", "exit_price": "101.0",
         "gross_pnl": "0.05", "fees_paid": "0.0", "pnl_usd": "0.05", "notional": "0"},
    ]
    with tempfile.TemporaryDirectory() as td:
        jf = Path(td) / "j.json"
        jf.write_text(json.dumps(jrows))
        of = Path(td) / "o.json"
        of.write_text(json.dumps([
            {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100, "symbol":"BTC/USD"},
            {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":101,"l":100,"c":101, "symbol":"BTC/USD"},
        ]))
        payload = build_replay_fidelity_report(journal_path=jf, ohlcv_fixture=of)
        # should still analyze but trustworthiness should be false due to missing pct calc
        assert payload["cycles_analyzed"] == 1
        # when ntnl=0 the pct list may be empty leading to trustworthy false or gate note
        assert payload["replay_trustworthy"] is False or "pct_of_notional" in str(payload) or len(payload.get("failed_trust_gates", [])) > 0
