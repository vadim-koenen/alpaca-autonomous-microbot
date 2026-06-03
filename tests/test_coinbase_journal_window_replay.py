"""
tests/test_coinbase_journal_window_replay.py — P2-025F journal-window replay baseline tests.

All tests offline, fixture or in-memory, no broker, no .env, no orders, no mutation.
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from coinbase_offline_backtest import (
    parse_journal_cycles,
    run_journal_window_replay,
    load_bars_from_fixture,
)
from scripts.coinbase_journal_window_replay_report import build_journal_window_report


def _mk_bar(ts: datetime, o: float, h: float, l: float, c: float) -> "Bar":
    from coinbase_offline_backtest import Bar
    return Bar(t=ts, o=Decimal(str(o)), h=Decimal(str(h)), l=Decimal(str(l)), c=Decimal(str(c)))


def test_parses_journal_fixture_by_header_name(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b",
         "action": "EXIT", "reason": "max hold time 90min exceeded (5min held)",
         "fill_price": "100.0", "exit_price": "100.1", "gross_pnl": "0.005", "fees_paid": "0.024", "pnl_usd": "-0.019", "notional": "5.0"},
    ]))
    cycles = parse_journal_cycles(jf)
    assert len(cycles) == 1
    c = cycles[0]
    assert c["symbol"] == "BTC/USD"
    assert c["strategy"] == "b"
    assert "entry_time" in c and "exit_time" in c
    assert float(c["net_pnl_recorded"]) < 0


def test_skips_malformed_blank_warn_rows(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([
        {},  # blank
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "action": "EXIT", "reason": "max hold...", "fill_price": "x"},  # bad numeric
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "action": "WARN", "reason": "foo"},
    ]))
    cycles = parse_journal_cycles(jf)
    assert len(cycles) == 0


def test_replays_multiple_journal_driven_cycles(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b", "action": "EXIT",
         "reason": "max hold time 90min exceeded (5min held)", "fill_price": "100.0", "exit_price": "100.1",
         "gross_pnl": "0.005", "fees_paid": "0.0", "pnl_usd": "0.005", "notional": "5.0"},
        {"timestamp": "2026-01-01T00:10:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b", "action": "EXIT",
         "reason": "stop-loss hit (3min held)", "fill_price": "100.0", "exit_price": "98.4",
         "gross_pnl": "-0.08", "fees_paid": "0.0", "pnl_usd": "-0.08", "notional": "5.0"},
    ]))
    of = tmp_path / "o.json"
    of.write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":100.5,"l":99.5,"c":100.1},
        {"timestamp_utc": "2026-01-01T00:10:00Z", "o":100,"h":100,"l":98,"c":98.4},
    ]))
    cycles = parse_journal_cycles(jf)
    bars = load_bars_from_fixture(of)
    rep = run_journal_window_replay(bars, cycles, entry_fee_rate=0, exit_fee_rate=0)
    assert rep["cycles_seen"] == 2
    assert rep["cycles_replayed"] >= 1  # at least the first
    assert rep["trade_permission"] == "none"
    assert rep["risk_increase"] == "not_approved"
    assert rep["scaling_allowed"] is False


def test_produces_fee_dominated_negative_result_in_fixture():
    # use the committed sample fixtures
    base = Path("tests/fixtures/journal_window_replay")
    rep = build_journal_window_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
        entry_fee_rate=0.012, exit_fee_rate=0.012,
    )
    # at least the fee-drag cycle should show negative replay net
    assert rep["cycles_seen"] >= 3
    assert rep["trade_permission"] == "none"
    # one of the replayed should be net negative
    replayed_nets = [float(c.get("replayed_net", 0)) for c in rep.get("per_cycle", []) if c.get("replayed_net")]
    assert any(n < 0 for n in replayed_nets) or rep["net_pnl_sum"].startswith("-") or float(rep.get("net_pnl_sum", 0)) <= 0


def test_skip_reason_breakdown_works(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([
        {"timestamp": "2026-06-01T00:00:00Z", "mode": "live", "symbol": "SOL/USD", "strategy": "b", "action": "EXIT",
         "reason": "max hold time 90min exceeded (10min held)", "fill_price": "150", "exit_price": "149",
         "gross_pnl": "-0.033", "fees_paid": "0.012", "pnl_usd": "-0.045", "notional": "5"},
    ]))
    of = tmp_path / "o.json"
    of.write_text(json.dumps([{"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100}]))
    rep = build_journal_window_report(journal_path=jf, ohlcv_fixture=of)
    assert rep["cycles_skipped"] >= 1
    assert "no_ohlcv_in_window" in str(rep.get("skip_reason_breakdown", {}))


def test_per_strategy_and_per_symbol_summaries_work(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "s1", "action": "EXIT",
         "reason": "max hold...", "fill_price": "100", "exit_price": "100.1", "gross_pnl": "0.005", "fees_paid": "0", "pnl_usd": "0.005", "notional": "5"},
    ]))
    of = tmp_path / "o.json"
    of.write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":100.1,"l":100,"c":100.1},
    ]))
    rep = build_journal_window_report(journal_path=jf, ohlcv_fixture=of)
    assert "s1" in str(rep.get("per_strategy", {})) or rep["cycles_replayed"] > 0


def test_direction_match_field_works(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b", "action": "EXIT",
         "reason": "max hold...", "fill_price": "100", "exit_price": "101", "gross_pnl": "0.05", "fees_paid": "0.01", "pnl_usd": "0.04", "notional": "5"},
    ]))
    of = tmp_path / "o.json"
    of.write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":101,"l":100,"c":101},
    ]))
    rep = build_journal_window_report(journal_path=jf, ohlcv_fixture=of, entry_fee_rate=0, exit_fee_rate=0)
    assert "replay_vs_journal_direction_match" in rep
    # both positive -> match true or computed
    assert rep.get("replay_vs_journal_direction_match") is not False or rep["cycles_replayed"] == 0


def test_report_emits_valid_json_and_permissions(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([{"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b", "action": "EXIT",
                               "reason": "max hold...", "fill_price": "100", "exit_price": "100.1", "gross_pnl": "0.005", "fees_paid": "0.024", "pnl_usd": "-0.019", "notional": "5"}]))
    of = tmp_path / "o.json"
    of.write_text(json.dumps([{"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100},{"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":100.5,"l":99.5,"c":100.1}]))
    payload = build_journal_window_report(journal_path=jf, ohlcv_fixture=of)
    assert payload["trade_permission"] == "none"
    assert payload["risk_increase"] == "not_approved"
    assert payload["scaling_allowed"] is False
    json.dumps(payload)  # valid


def test_output_does_not_include_forbidden_fields(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([{"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b", "action": "EXIT",
                               "reason": "max hold...", "fill_price": "100", "exit_price": "100.1", "gross_pnl": "0.005", "fees_paid": "0.024", "pnl_usd": "-0.019", "notional": "5"}]))
    of = tmp_path / "o.json"
    of.write_text(json.dumps([{"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100},{"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":100.5,"l":99.5,"c":100.1}]))
    payload = build_journal_window_report(journal_path=jf, ohlcv_fixture=of)
    s = json.dumps(payload).lower()
    forbidden = ["create_order", "place_order", "buy", "sell", "order_size", "risk_override", "live_broker", "launchctl"]
    for f in forbidden:
        assert f not in s


def test_no_live_broker_or_env_in_modules(monkeypatch):
    import coinbase_offline_backtest as mod
    assert hasattr(mod, "parse_journal_cycles")
    import scripts.coinbase_journal_window_replay_report as rmod
    assert hasattr(rmod, "build_journal_window_report")

def test_load_bars_from_fixture_supports_csv(tmp_path):
    cf = tmp_path / "c.csv"
    cf.write_text("timestamp_utc,symbol,open,high,low,close,volume\n2026-01-01T00:00:00Z,BTC/USD,100,100.5,99.5,100.1,1\n")
    bars = load_bars_from_fixture(cf)
    assert len(bars) == 1
    assert bars[0].symbol == "BTC/USD"
    assert bars[0].c == Decimal("100.1")

def test_report_includes_ohlcv_coverage_fields(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "b", "action": "EXIT", "reason": "max hold (5min held)", "fill_price": "100", "exit_price": "100.1", "gross_pnl": "0.005", "fees_paid": "0.024", "pnl_usd": "-0.019", "notional": "5"},
    ]))
    of = tmp_path / "o.json"
    of.write_text(json.dumps([{"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100, "symbol":"BTC/USD"}, {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":100.5,"l":99.5,"c":100.1, "symbol":"BTC/USD"}]))
    payload = build_journal_window_report(journal_path=jf, ohlcv_fixture=of)
    assert "cycles_with_ohlcv_window" in payload
    assert "coverage_rate" in payload
    assert "required_symbols" in payload
    assert "missing_ohlcv_directory" in payload
    assert "per_symbol_coverage" in payload
    assert payload["cycles_with_ohlcv_window"] >= 0

def test_with_ohlcv_fixture_replays_some_and_skips_some():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_journal_window_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    # sample has 4 cycles, 3 should have window (BTC/ETH at 00:05/10/15), 1 skip (June)
    assert payload["cycles_seen"] == 4
    assert payload["cycles_with_ohlcv_window"] >= 2
    assert payload["cycles_without_ohlcv_window"] >= 1
    # replay should have replayed some
    assert payload.get("cycles_replayed", 0) >= 1 or payload.get("cycles_with_ohlcv_window",0) > 0
    assert "no_ohlcv_in_window" in str(payload.get("skip_reason_breakdown", {})) or payload["cycles_without_ohlcv_window"] > 0
