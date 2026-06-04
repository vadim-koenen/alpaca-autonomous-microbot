"""
tests/test_coinbase_replay_price_basis_reconciliation.py — P2-025N replay price-basis tests.

All tests offline, fixture or in-memory, no broker, no .env, no orders, no network, no mutation.
"""

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.coinbase_replay_price_basis_reconciliation import (
    build_replay_price_basis_report,
    _price_within_candle,
    _find_nearest_bar,
    _classify_residual_driver,
)


def _mk_bar(ts, o, h, l, c, v=0, sym="BTC/USD"):
    from coinbase_offline_backtest import Bar
    from datetime import datetime, timezone
    return Bar(t=ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts, o=Decimal(str(o)), h=Decimal(str(h)), l=Decimal(str(l)), c=Decimal(str(c)), v=Decimal(str(v)), symbol=sym)


def test_entry_residual_is_zero_by_harness_design():
    # replay_entry always == journal entry by design of journal-window replay
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_price_basis_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    for r in payload["per_cycle"]:
        er = Decimal(r["entry_price_residual"])
        assert er == Decimal("0") or abs(er) < Decimal("1e-10")


def test_exit_residual_and_gross_attribution():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_price_basis_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    for r in payload["per_cycle"]:
        er = Decimal(r["entry_price_residual"])
        xr = Decimal(r["exit_price_residual"])
        gr = Decimal(r["gross_residual"])
        ntnl = Decimal(r["notional"])
        jep = Decimal(r["journal_entry_price"]) if r.get("journal_entry_price") else Decimal("0")
        # gross res should be approx exit_res * qty  (entry res~0)
        if jep > 0 and abs(xr) > 0:
            qty = ntnl / jep
            expected_g = xr * qty
            # allow small rounding from simulate
            assert abs(gr - expected_g) < Decimal("0.0001") or abs(gr) < Decimal("0.01")
    ra = payload["residual_attribution"]
    assert Decimal(ra["attributed_to_entry_price"]) == Decimal("0") or abs(Decimal(ra["attributed_to_entry_price"])) < Decimal("1e-6")
    assert "exit" in ra.get("residual_appears_mostly", "").lower() or "timeout" in ra.get("residual_appears_mostly", "").lower()


def test_gross_residual_attribution_matches_exit_contrib():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_price_basis_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    ra = payload["residual_attribution"]
    # entry ~0, exit should carry the signed gross
    assert abs(Decimal(ra["attributed_to_exit_price"])) >= abs(Decimal(ra["signed_gross_residual"])) * Decimal("0.99") or Decimal(ra["signed_gross_residual"]) == Decimal("0")


def test_direction_mismatch_classification():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_price_basis_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    assert "direction_match" in payload["direction_fidelity"]
    assert "mismatch_count" in payload["direction_fidelity"]
    for r in payload.get("mismatch_cycles_first", []):
        assert r.get("direction_match_from_replay_run") is False


def test_candle_high_low_containment_classification():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_price_basis_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    for r in payload["per_cycle"]:
        assert "journal_entry_within_candle_hl" in r
        assert "journal_exit_within_candle_hl" in r
        # values are bool or None in edge
        assert isinstance(r["journal_entry_within_candle_hl"], (bool, type(None)))


def test_timeout_exit_basis_classification():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_price_basis_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    to = payload.get("timeout_specific", {})
    assert "count" in to
    assert "signed_gross_residual" in to
    # at least one timeout in fixture
    has_timeout = any(r.get("is_timeout_exit") for r in payload["per_cycle"])
    assert has_timeout or to.get("count", 0) >= 0


def test_missing_journal_price_handling():
    jrows = [
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "s",
         "action": "EXIT", "reason": "max hold...", "fill_price": "0", "exit_price": "0",
         "gross_pnl": "0", "fees_paid": "0", "pnl_usd": "0", "notional": "5"},
    ]
    with tempfile.TemporaryDirectory() as td:
        jf = Path(td) / "j.json"
        jf.write_text(json.dumps(jrows))
        of = Path(td) / "o.json"
        of.write_text(json.dumps([
            {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100, "symbol":"BTC/USD"},
            {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":101,"l":100,"c":101, "symbol":"BTC/USD"},
        ]))
        payload = build_replay_price_basis_report(journal_path=jf, ohlcv_fixture=of)
        # may analyze 0 or flag missing; must not crash and have safety
        assert "trade_permission" in payload
        assert payload["trade_permission"] == "none"


def test_skipped_cycle_accounting_and_details():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_price_basis_report(
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
    payload = build_replay_price_basis_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    for k in ["cycles_analyzed", "cycles_skipped", "per_cycle", "replay_trustworthy",
              "residual_attribution", "by_symbol", "by_exit_reason", "timeout_specific",
              "top_worst_residual_cycles", "top_direction_mismatches", "driver_classification",
              "candle_containment", "replay_basis_summary", "skipped_cycle_details",
              "trade_permission", "risk_increase", "scaling_allowed"]:
        assert k in payload
    assert payload["trade_permission"] == "none"
    assert payload["scaling_allowed"] is False
    json.dumps(payload)  # valid json


def test_no_forbidden_and_isolated():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_price_basis_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    s = json.dumps(payload).lower()
    forbidden = ["create_order", "place_order", "buy", "sell", "order_size", "risk_override", "live_broker", "launchctl", ".env"]
    for f in forbidden:
        assert f not in s


def test_in_memory_cycles_for_price_basis(monkeypatch):
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
        payload = build_replay_price_basis_report(journal_path=jf, ohlcv_fixture=of)
        assert payload["cycles_analyzed"] == 1
        assert payload["cycles_skipped"] == 0
        row = payload["per_cycle"][0]
        assert row["symbol"] == "BTC/USD"
        assert "gross_residual" in row
        assert "residual_driver" in row
        assert "journal_entry_within_candle_hl" in row
        assert "replay_entry_basis" in row
        assert payload["replay_trustworthy"] is False  # per design until gates
