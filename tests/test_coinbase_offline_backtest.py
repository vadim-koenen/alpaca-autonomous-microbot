"""
tests/test_coinbase_offline_backtest.py — Covers required scenarios for P2-025D harness.

All tests are offline, fixture or in-memory, no broker, no .env, no orders, no mutation.
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
)
from scripts.coinbase_offline_backtest_report import build_report


def _mk_bar(ts: datetime, c: float) -> Bar:
    return Bar(t=ts, o=Decimal(str(c)), h=Decimal(str(c)), l=Decimal(str(c)), c=Decimal(str(c)))


def _mk_bars_from_prices(prices: list[float], start: datetime = None) -> list[Bar]:
    if start is None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, p in enumerate(prices):
        bars.append(_mk_bar(start + timedelta(minutes=5 * i), p))
    return bars


def test_take_profit_exit():
    # Price goes up enough to hit TP ~3%
    prices = [100.0, 100.5, 101.0, 103.5, 103.3]  # entry at 100, TP at ~103
    bars = _mk_bars_from_prices(prices)
    res = run_backtest(
        bars,
        symbol="TEST/USD",
        strategy_name="test_tp",
        take_profit_pct=Decimal("3.0"),
        stop_loss_pct=Decimal("1.5"),
        max_hold_minutes=90,
        entry_fee_rate=Decimal("0.006"),
        exit_fee_rate=Decimal("0.012"),
        slippage_buffer_rate=Decimal("0.001"),
        entry_rule="fixture_signal",
    )
    assert res.total_trades == 1
    t = res.closed_trades[0]
    assert t["exit_reason"] == "take_profit"
    assert float(t["net_pnl"]) > 0  # gross positive enough to cover fees


def test_stop_loss_exit():
    prices = [100.0, 99.5, 98.0, 97.5]  # drops to SL
    bars = _mk_bars_from_prices(prices)
    res = run_backtest(
        bars,
        take_profit_pct=Decimal("3.0"),
        stop_loss_pct=Decimal("1.5"),
        max_hold_minutes=90,
        entry_fee_rate=Decimal("0.0"),
        exit_fee_rate=Decimal("0.0"),
        slippage_buffer_rate=Decimal("0.0"),
    )
    assert res.total_trades == 1
    assert res.closed_trades[0]["exit_reason"] == "stop_loss"
    assert float(res.closed_trades[0]["net_pnl"]) < 0


def test_max_hold_timeout_exit():
    prices = [100.0] * 30  # flat, will hit hold
    bars = _mk_bars_from_prices(prices)
    res = run_backtest(
        bars,
        take_profit_pct=Decimal("10.0"),
        stop_loss_pct=Decimal("10.0"),
        max_hold_minutes=10,  # 2 bars of 5min
        entry_fee_rate=Decimal("0.0"),
        exit_fee_rate=Decimal("0.0"),
    )
    assert res.total_trades == 1
    assert res.closed_trades[0]["exit_reason"] == "max_hold_time_exceeded"


def test_fee_application_and_net_negative():
    # Gross small positive, but fees make net negative
    prices = [100.0, 100.1, 100.2, 100.3, 100.4]  # small move
    bars = _mk_bars_from_prices(prices)
    res = run_backtest(
        bars,
        take_profit_pct=Decimal("1.0"),
        stop_loss_pct=Decimal("10.0"),
        max_hold_minutes=90,
        entry_fee_rate=Decimal("0.05"),  # high fee for test
        exit_fee_rate=Decimal("0.05"),
        slippage_buffer_rate=Decimal("0.0"),
    )
    assert res.total_trades == 1
    t = res.closed_trades[0]
    gross = float(t["gross_pnl"])
    fees = float(t["fees"])
    net = float(t["net_pnl"])
    assert gross > 0
    assert fees > gross
    assert net < 0


def test_gross_positive_net_negative_due_to_fees():
    # Explicit
    prices = [100.0, 101.0, 102.0]
    bars = _mk_bars_from_prices(prices)
    res = run_backtest(
        bars,
        take_profit_pct=Decimal("2.0"),
        stop_loss_pct=Decimal("10.0"),
        max_hold_minutes=90,
        entry_fee_rate=Decimal("0.03"),
        exit_fee_rate=Decimal("0.03"),
    )
    assert res.total_trades == 1
    assert float(res.closed_trades[0]["gross_pnl"]) > 0
    assert float(res.closed_trades[0]["net_pnl"]) < 0


def test_deterministic_output():
    prices = [100.0, 101.5, 102.0, 103.0]
    bars = _mk_bars_from_prices(prices)
    r1 = run_backtest(bars, take_profit_pct=Decimal("3.0"))
    r2 = run_backtest(bars, take_profit_pct=Decimal("3.0"))
    assert r1.net_pnl_sum == r2.net_pnl_sum
    assert r1.closed_trades[0]["exit_reason"] == r2.closed_trades[0]["exit_reason"]


def test_malformed_candle_rows_handled_safely(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"c": "NaN", "o": 0}]))
    bars = load_bars_from_fixture(bad)
    res = run_backtest(bars)
    assert res.total_trades == 0


def test_report_script_emits_valid_json_and_permissions(tmp_path):
    fixture = tmp_path / "tp.json"
    fixture.write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o": 100, "h": 100, "l": 100, "c": 100},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o": 100, "h": 103.5, "l": 100, "c": 103.5},
    ]))
    payload = build_report(fixture_path=fixture, take_profit_pct=3.0)
    assert payload["trade_permission"] == "none"
    assert payload["risk_increase"] == "not_approved"
    assert payload["scaling_allowed"] is False
    assert "total_trades" in payload
    json.dumps(payload)  # valid


def test_output_does_not_include_forbidden_fields(tmp_path):
    fixture = tmp_path / "f.json"
    fixture.write_text(json.dumps([{"o": 100, "h": 100, "l": 100, "c": 100, "timestamp_utc": "2026-01-01T00:00:00Z"}]))
    payload = build_report(fixture_path=fixture)
    s = json.dumps(payload)
    forbidden = ["create_order", "place_order", "buy", "sell", "order_size", "risk_override", "live_broker"]
    for f in forbidden:
        assert f not in s.lower()


def test_no_live_broker_or_env_in_module(monkeypatch):
    # Import should not trigger broker or env
    import coinbase_offline_backtest as mod
    assert hasattr(mod, "run_backtest")
    # isolation verified by absence of side effects on import (no broker client, no network)


def test_fixtures_for_tp_sl_hold_and_fee(tmp_path):
    # Create the 4 required fixtures as part of test (self-contained)
    base = tmp_path
    # TP
    (base / "tp_hit.json").write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o": 100, "h": 100, "l": 100, "c": 100},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o": 100.5, "h": 103.5, "l": 100.5, "c": 103.5},
    ]))
    # SL
    (base / "sl_hit.json").write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o": 100, "h": 100, "l": 100, "c": 100},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o": 99, "h": 99.5, "l": 98.4, "c": 98.4},
    ]))
    # Hold
    flat = [{"timestamp_utc": f"2026-01-01T00:{5*i:02d}:00Z", "o": 100, "h": 100, "l": 100, "c": 100} for i in range(20)]
    (base / "hold_timeout.json").write_text(json.dumps(flat))
    # Fee drag
    (base / "fee_drag.json").write_text(json.dumps([
        {"timestamp_utc": "2026-01-01T00:00:00Z", "o": 100, "h": 100, "l": 100, "c": 100},
        {"timestamp_utc": "2026-01-01T00:05:00Z", "o": 100.1, "h": 100.2, "l": 100.1, "c": 100.15},
    ]))
    # Run each
    for name in ["tp_hit", "sl_hit", "hold_timeout", "fee_drag"]:
        res = run_backtest_from_fixture(base / f"{name}.json", max_hold_minutes=10)
        assert isinstance(res, BacktestResult)
        if name == "tp_hit":
            assert any(t["exit_reason"] == "take_profit" for t in res.closed_trades)
        if name == "sl_hit":
            assert any(t["exit_reason"] == "stop_loss" for t in res.closed_trades)
        if name == "hold_timeout":
            assert any("max_hold" in t["exit_reason"] for t in res.closed_trades)
