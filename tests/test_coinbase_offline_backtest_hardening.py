"""
tests/test_coinbase_offline_backtest_hardening.py — P2-025E hardening tests for intra-bar, fee scenarios, policies, journal replay, report fields.

All tests offline/fixture-only. No broker, no .env, no orders, no mutation.
"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from coinbase_offline_backtest import (
    BacktestResult,
    Bar,
    load_bars_from_fixture,
    run_backtest,
    run_backtest_from_fixture,
    run_backtest_with_journal_entries,
)
from scripts.coinbase_offline_backtest_report import build_report


def _mk_bar(ts: datetime, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(t=ts, o=Decimal(str(o)), h=Decimal(str(h)), l=Decimal(str(l)), c=Decimal(str(c)))


def _mk_bars_from_prices(prices: list[float], start: datetime = None) -> list[Bar]:
    if start is None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, p in enumerate(prices):
        bars.append(_mk_bar(start + timedelta(minutes=5 * i), p, p, p, p))
    return bars


def test_intra_bar_tp_exit():
    # fixture: high crosses TP but close does not; intra must catch TP
    res = run_backtest_from_fixture(
        "tests/fixtures/offline_backtest/intra_bar_tp.json",
        take_profit_pct=3.0,
        stop_loss_pct=1.5,
        max_hold_minutes=90,
        entry_fee_rate=0.0,
        exit_fee_rate=0.0,
    )
    assert res.total_trades == 1
    assert res.closed_trades[0]["exit_reason"] == "take_profit"


def test_intra_bar_sl_exit():
    res = run_backtest_from_fixture(
        "tests/fixtures/offline_backtest/intra_bar_sl.json",
        take_profit_pct=3.0,
        stop_loss_pct=1.5,
        max_hold_minutes=90,
        entry_fee_rate=0.0,
        exit_fee_rate=0.0,
    )
    assert res.total_trades == 1
    assert res.closed_trades[0]["exit_reason"] == "stop_loss"


def test_both_tp_sl_same_bar_chooses_stop_loss():
    # high > TP and low < SL in same bar -> SL precedence
    res = run_backtest_from_fixture(
        "tests/fixtures/offline_backtest/both_tp_sl_same_bar.json",
        take_profit_pct=3.0,
        stop_loss_pct=1.5,
        max_hold_minutes=90,
        entry_fee_rate=0.0,
        exit_fee_rate=0.0,
    )
    assert res.total_trades == 1
    assert res.closed_trades[0]["exit_reason"] == "stop_loss"


def test_sl_before_tp_precedence_explicit():
    # in-mem equivalent
    bars = [
        _mk_bar(datetime(2026,1,1,tzinfo=timezone.utc), 100,100,100,100),
        _mk_bar(datetime(2026,1,1,0,5,tzinfo=timezone.utc), 100.5, 103.5, 98.0, 99.5),
    ]
    res = run_backtest(bars, take_profit_pct=3.0, stop_loss_pct=1.5, entry_fee_rate=0, exit_fee_rate=0)
    assert res.total_trades == 1
    assert res.closed_trades[0]["exit_reason"] == "stop_loss"


def test_taker_taker_default_is_conservative():
    # use fee comparison fixture: ~2% gross move, taker roundtrip 2.4% -> net neg
    res = run_backtest_from_fixture(
        "tests/fixtures/offline_backtest/fee_scenario_comparison.json",
        # defaults now 0.012/0.012
    )
    assert res.total_trades == 1
    assert float(res.closed_trades[0]["gross_pnl"]) > 0
    assert float(res.closed_trades[0]["net_pnl"]) < 0
    assert res.fee_scenario == "taker/taker"
    assert res.percent_trades_clearing_fee_hurdle < 100.0


def test_maker_maker_optional_scenario_via_rates():
    res = run_backtest_from_fixture(
        "tests/fixtures/offline_backtest/fee_scenario_comparison.json",
        entry_fee_rate=0.006,
        exit_fee_rate=0.006,
    )
    assert res.total_trades == 1
    assert float(res.closed_trades[0]["gross_pnl"]) > 0
    assert float(res.closed_trades[0]["net_pnl"]) > 0  # clears under maker
    assert res.round_trip_fee_rate.startswith("0.012000")  # fmt_rate precision tolerant



def test_gross_positive_net_negative_under_taker_but_passes_maker():
    # explicit rates
    bars = _mk_bars_from_prices([100.0, 102.0])
    r_taker = run_backtest(bars, take_profit_pct=3.0, entry_fee_rate=0.012, exit_fee_rate=0.012)
    r_maker = run_backtest(bars, take_profit_pct=3.0, entry_fee_rate=0.006, exit_fee_rate=0.006)
    assert float(r_taker.closed_trades[0]["gross_pnl"]) > 0
    assert float(r_taker.closed_trades[0]["net_pnl"]) < 0
    assert float(r_maker.closed_trades[0]["net_pnl"]) > 0
    assert r_taker.percent_trades_clearing_fee_hurdle == 0.0 or r_taker.percent_trades_clearing_fee_hurdle < 100
    assert r_maker.percent_trades_clearing_fee_hurdle == 100.0


def test_cleared_fee_hurdle_and_percent_fields():
    res = run_backtest_from_fixture(
        "tests/fixtures/offline_backtest/fee_scenario_comparison.json",
        entry_fee_rate=0.006, exit_fee_rate=0.006,
    )
    assert "cleared_fee_hurdle" in dir(res) or hasattr(res, "cleared_fee_hurdle")
    assert res.cleared_fee_hurdle in (True, False)
    assert 0.0 <= res.percent_trades_clearing_fee_hurdle <= 100.0


def test_exit_policy_static_and_live_atr_deterministic_selection():
    bars = _mk_bars_from_prices([100.0, 101.5, 103.5])
    r_static = run_backtest(bars, exit_policy="static")
    r_atr = run_backtest(bars, exit_policy="live_atr")
    assert r_static.exit_policy == "static"
    assert r_atr.exit_policy == "live_atr"
    # placeholder uses same logic => deterministic same aggregates
    assert r_static.net_pnl_sum == r_atr.net_pnl_sum
    assert "live_atr placeholder" in " ".join(r_atr.notes)


def test_journal_driven_multiple_entries():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(10):
        p = 100.0 + i * 0.5
        bars.append(_mk_bar(start + timedelta(minutes=5*i), p, p, p, p))
    jentries = [
        {"entry_time": "2026-01-01T00:00:00Z", "entry_price": "100.0", "notional": "5.0", "symbol": "BTC/USD", "strategy_name": "jtest"},
        {"entry_time": "2026-01-01T00:15:00Z", "entry_price": "101.5", "notional": "5.0", "symbol": "BTC/USD", "strategy_name": "jtest"},
    ]
    res = run_backtest_with_journal_entries(
        bars, jentries,
        entry_fee_rate=0.0, exit_fee_rate=0.0,
        take_profit_pct=3.0,
    )
    assert res.total_trades == 2
    assert any("journal" in n.lower() for n in res.notes)
    assert res.exit_reason_breakdown  # some exits


def test_report_emits_all_p2_025e_required_fields_and_safety(tmp_path):
    fixture = tmp_path / "f.json"
    fixture.write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o":100,"h":100,"l":100,"c":100},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o":100.5,"h":103.5,"l":100.5,"c":103.5},
    ]))
    payload = build_report(
        fixture_path=fixture,
        take_profit_pct=3.0,
        exit_policy="static",
        fee_scenario="taker/taker",
    )
    required = [
        "schema_version", "exit_policy", "fee_scenario",
        "total_trades", "wins", "losses", "breakeven", "win_rate",
        "gross_pnl_sum", "fees_sum", "net_pnl_sum",
        "net_pnl_per_trade", "percent_trades_clearing_fee_hurdle",
        "exit_reason_breakdown",
        "trade_permission", "risk_increase", "scaling_allowed",
        "notes",
    ]
    for k in required:
        assert k in payload, f"missing {k}"
    assert payload["trade_permission"] == "none"
    assert payload["risk_increase"] == "not_approved"
    assert payload["scaling_allowed"] is False
    assert payload["exit_policy"] == "static"
    assert payload["fee_scenario"] == "taker/taker"
    assert "parameters" in payload and "exit_policy" in payload["parameters"]
    s = json.dumps(payload).lower()
    forbidden = ["create_order", "place_order", "cancel_order", "close_position", "buy", "sell", "order_size", "risk_override", "live_broker", "launchctl", ".env"]
    for f in forbidden:
        assert f not in s


def test_report_journal_driven_fields(tmp_path):
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([
        {"symbol":"BTC/USD","strategy_name":"j","entry_time":"2026-01-01T00:00:00Z","entry_price":"100.0","notional":"5.0"},
    ]))
    of = tmp_path / "o.json"
    of.write_text(json.dumps([
        {"timestamp_utc":"2026-01-01T00:00:00Z","o":100,"h":100,"l":100,"c":100},
        {"timestamp_utc":"2026-01-01T00:05:00Z","o":100.5,"h":103.5,"l":100.5,"c":103.5},
    ]))
    payload = build_report(journal_fixture=jf, ohlcv_fixture=of, exit_policy="static")
    assert "journal_fixture" in payload
    assert "ohlcv_fixture" in payload
    assert payload["total_trades"] >= 1
    assert payload["trade_permission"] == "none"


def test_no_forbidden_in_hardening_module(monkeypatch):
    import coinbase_offline_backtest as mod
    src = open(mod.__file__).read().lower()
    for bad in ["create_order", "place_order", "launchctl", "live-read-only"]:
        assert bad not in src
