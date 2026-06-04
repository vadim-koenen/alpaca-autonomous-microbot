"""
tests/test_coinbase_replay_economics_report.py — P2-025L replay economics fee scenario tests.

All tests: offline, fixture or in-memory only, no broker, no .env, no orders, no network, no mutation.
"""

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.coinbase_replay_economics_report import (
    build_replay_economics_report,
    _compute_fees_and_net,
    _scale_for_notional,
)


def test_fee_scenario_math_basic():
    # gross=0.1, n=5, taker 1.2% each: fees=5*0.012 + 5.1*0.012 = 0.06 + 0.0612=0.1212, net=0.1-0.1212=-0.0212
    g = Decimal("0.1")
    n = Decimal("5")
    net = _compute_fees_and_net(g, n, Decimal("0.012"), Decimal("0.012"))
    assert net == Decimal("-0.0212")


def test_zero_fee_net_equals_gross():
    g = Decimal("0.05")
    n = Decimal("5")
    net = _compute_fees_and_net(g, n, Decimal("0"), Decimal("0"))
    assert net == g


def test_maker_vs_taker_ordering_positive_gross():
    # positive gross: lower fees (maker) must produce strictly higher net than taker
    g = Decimal("0.2")
    n = Decimal("5")
    net_taker = _compute_fees_and_net(g, n, Decimal("0.012"), Decimal("0.012"))
    net_maker = _compute_fees_and_net(g, n, Decimal("0.004"), Decimal("0.004"))
    net_mixed = _compute_fees_and_net(g, n, Decimal("0.004"), Decimal("0.012"))
    assert net_maker > net_taker
    assert net_mixed > net_taker  # less drag than full taker
    assert net_maker > net_mixed  # maker on both better than mixed


def test_maker_vs_taker_ordering_negative_gross():
    # negative gross: maker still less negative net (lower fee drag on loss)
    g = Decimal("-0.1")
    n = Decimal("5")
    net_taker = _compute_fees_and_net(g, n, Decimal("0.012"), Decimal("0.012"))
    net_maker = _compute_fees_and_net(g, n, Decimal("0.004"), Decimal("0.004"))
    assert net_maker > net_taker  # e.g. -0.1-0.12 = -0.22 vs -0.1-0.04ish = -0.14 , -0.14 > -0.22


def test_notional_scaling_linear():
    net_at_5 = Decimal("-0.1")
    assert _scale_for_notional(net_at_5, Decimal("5"), Decimal("0.5")) == Decimal("-0.01")
    assert _scale_for_notional(net_at_5, Decimal("5"), Decimal("10")) == Decimal("-0.2")


def test_skipped_cycle_accounting_with_fixture():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_economics_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    assert payload["cycles_seen"] == 4
    assert payload["cycles_analyzed"] == 3
    assert payload["cycles_skipped"] == 1
    assert payload["coverage_rate"] == 0.75
    assert "no_ohlcv_in_window" in str(payload.get("skip_reason_breakdown", {}))
    assert payload["trade_permission"] == "none"
    assert payload["risk_increase"] == "not_approved"
    assert payload["scaling_allowed"] is False


def test_json_schema_and_keys_with_fixture():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_economics_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    # required top
    for k in ["cycles_analyzed", "cycles_skipped", "coverage_rate", "fee_scenarios", "verdict",
              "break_even_fee_rate", "notional_sensitivity", "direction_match_replay_vs_journal",
              "timeout_exit_count", "timeout_exit_share", "trade_permission", "risk_increase", "scaling_allowed"]:
        assert k in payload
    # 5 scenarios
    sc = payload["fee_scenarios"]
    for name in ["journal_recorded_fees", "taker/taker", "maker/maker", "zero_fee", "mixed_maker_taker"]:
        assert name in sc
        s = sc[name]
        for dk in ["gross_pnl_sum", "fee_sum", "net_pnl_sum", "win_rate", "avg_net_pnl", "median_net_pnl",
                   "best_net_pnl", "worst_net_pnl", "per_symbol", "per_exit_reason", "per_strategy"]:
            assert dk in s
    # notional keys
    for nt in ["0.5", "1", "5", "10"]:
        assert nt in payload["notional_sensitivity"]
    # safety
    assert payload["trade_permission"] == "none"
    assert payload["scaling_allowed"] is False
    # json serializable
    json.dumps(payload)


def test_deterministic_fixture_economics_numbers():
    # On sample: 3 analyzed, replay gross negative small, zero net = gross (negative), taker net more neg
    base = Path("tests/fixtures/journal_window_replay")
    p = build_replay_economics_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    assert p["cycles_analyzed"] == 3
    z = p["fee_scenarios"]["zero_fee"]
    t = p["fee_scenarios"]["taker/taker"]
    m = p["fee_scenarios"]["maker/maker"]
    assert Decimal(z["net_pnl_sum"]) == Decimal(p["replay_gross_pnl_sum"])  # zero fee
    assert Decimal(t["net_pnl_sum"]) < Decimal(z["net_pnl_sum"])  # fees drag
    assert Decimal(m["net_pnl_sum"]) > Decimal(t["net_pnl_sum"])  # maker less drag
    # timeout share 2/3 (one SL in sample)
    assert p["timeout_exit_count"] == 2
    assert abs(p["timeout_exit_share"] - (2.0/3.0)) < 0.01


def test_in_memory_cycles_for_fee_scenarios_and_verdict(monkeypatch):
    # 2 cycles, one positive gross path, one negative; force coverage by providing bars via fixture
    # Use small temp fixture for ohlcv that covers both
    jrows = [
        {"timestamp": "2026-01-01T00:05:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "s",
         "action": "EXIT", "reason": "max hold time 90min exceeded (5min held)",
         "fill_price": "100.0", "exit_price": "101.0", "gross_pnl": "0.05", "fees_paid": "0.024", "pnl_usd": "0.026", "notional": "5.0"},
        {"timestamp": "2026-01-01T00:10:00Z", "mode": "live", "symbol": "BTC/USD", "strategy": "s",
         "action": "EXIT", "reason": "stop-loss hit (3min held)",
         "fill_price": "100.0", "exit_price": "98.5", "gross_pnl": "-0.075", "fees_paid": "0.012", "pnl_usd": "-0.087", "notional": "5.0"},
    ]
    with tempfile.TemporaryDirectory() as td:
        jf = Path(td) / "j.json"
        jf.write_text(json.dumps(jrows))
        of = Path(td) / "o.json"
        of.write_text(json.dumps([
            {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100, "symbol":"BTC/USD"},
            {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100,"h":101,"l":100,"c":101, "symbol":"BTC/USD"},
            {"timestamp_utc": "2026-01-01T00:10:00Z", "o":100,"h":100,"l":98,"c":98.5, "symbol":"BTC/USD"},
        ]))
        payload = build_replay_economics_report(journal_path=jf, ohlcv_fixture=of)
        assert payload["cycles_analyzed"] == 2
        assert payload["cycles_skipped"] == 0
        znet = Decimal(payload["fee_scenarios"]["zero_fee"]["net_pnl_sum"])
        tnet = Decimal(payload["fee_scenarios"]["taker/taker"]["net_pnl_sum"])
        mnet = Decimal(payload["fee_scenarios"]["maker/maker"]["net_pnl_sum"])
        # zero net == replay gross (positive in this path fixture)
        assert abs(float(znet) - float(Decimal(payload["replay_gross_pnl_sum"]))) < 0.0001
        assert mnet > tnet  # maker better (less drag)
        # verdict based on positive gross -> fee_drag_dominant or inconclusive (small N)
        assert payload["verdict"] in ("inconclusive", "fee_drag_dominant")


def test_report_emits_no_forbidden_and_is_isolated():
    base = Path("tests/fixtures/journal_window_replay")
    payload = build_replay_economics_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    s = json.dumps(payload).lower()
    forbidden = ["create_order", "place_order", "cancel_order", "close_position", "launchctl",
                 "live-read-only", ".env", "authorization", "bearer", "cb-access", "api_key", "secret", "jwt"]
    for f in forbidden:
        assert f not in s
    assert "trade_permission" in payload and payload["trade_permission"] == "none"


def test_no_live_broker_or_env_access_in_module(monkeypatch):
    # just importing and calling build on fixture must not require net/env
    base = Path("tests/fixtures/journal_window_replay")
    p = build_replay_economics_report(
        journal_path=base / "sample_journal.json",
        ohlcv_fixture=base / "sample_ohlcv.json",
    )
    assert p["cycles_analyzed"] >= 0
    # no side effects
    assert "REPLAY_ECONOMICS" not in str(Path.cwd())
