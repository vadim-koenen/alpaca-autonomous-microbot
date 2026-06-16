"""
tests/test_p2_044h_analyze_live_journal.py — P2-044H tests.
Pure stdlib + pytest. No broker, no network. Deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import analyze_live_journal as az

HEADER = ("timestamp,mode,asset_class,symbol,strategy,action,decision,reason,confidence,"
          "price,bid,ask,spread_pct,notional,qty,order_type,order_id,client_order_id,"
          "intent_key,status,fill_price,exit_price,gross_pnl,fees_paid,pnl_usd,pnl_pct,"
          "equity,buying_power,open_positions,daily_trade_count,consecutive_losses,error")


def _row(symbol, qty, fill, exitp, gross, fees, action="EXIT"):
    cols = [""] * 32
    cols[3] = symbol; cols[4] = "s"; cols[5] = action
    cols[14] = str(qty); cols[20] = str(fill); cols[21] = str(exitp)
    cols[22] = str(gross); cols[23] = str(fees)
    return ",".join(cols)


def _write(tmp_path, rows):
    p = tmp_path / "j.csv"
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    return p


def test_load_exits_filters_non_exit_and_zero_position(tmp_path):
    p = _write(tmp_path, [
        _row("BTC/USD", 1.0, 100.0, 101.0, 1.0, 0.5),
        _row("ETH/USD", 0.0, 0.0, 0.0, 0.0, 0.0),           # zero position -> skipped
        _row("BTC/USD", 1.0, 100.0, 100.0, 0.0, 0.5, action="ENTRY"),  # not EXIT
    ])
    rows = az.load_exits(p)
    assert len(rows) == 1
    assert rows[0].position_value == pytest.approx(100.0)
    assert rows[0].gross_return == pytest.approx(0.01)


def test_no_edge_diagnosis(tmp_path):
    # All gross negative before fees -> NO_EDGE.
    p = _write(tmp_path, [
        _row("BTC/USD", 1.0, 100.0, 99.5, -0.5, 0.2),
        _row("ETH/USD", 1.0, 100.0, 99.8, -0.2, 0.2),
        _row("SOL/USD", 1.0, 100.0, 100.1, 0.1, 0.2),
    ])
    a = az.analyze(az.load_exits(p))
    assert a["diagnosis"] == "NO_EDGE"
    # zero-fee venue still loses
    assert a["venue_repricing"]["alpaca_equities"]["net_usd"] < 0


def test_edge_exists_fees_binding(tmp_path):
    # Big gross edge that beats the cheapest venue cost -> real path exists.
    p = _write(tmp_path, [_row("BTC/USD", 1.0, 100.0, 103.0, 3.0, 1.5) for _ in range(5)])
    a = az.analyze(az.load_exits(p))
    assert a["diagnosis"] == "EDGE_EXISTS_FEES_BINDING"
    assert a["gross_return_per_trade"]["mean_pct"] == pytest.approx(3.0, abs=1e-6)


def test_venue_repricing_monotonic(tmp_path):
    p = _write(tmp_path, [_row("BTC/USD", 1.0, 100.0, 101.0, 1.0, 0.5) for _ in range(4)])
    a = az.analyze(az.load_exits(p))
    v = a["venue_repricing"]
    assert v["alpaca_equities"]["net_usd"] > v["alpaca_crypto"]["net_usd"] \
        > v["coinbase_maker"]["net_usd"] > v["coinbase_taker"]["net_usd"]


def test_main_writes_outputs(tmp_path):
    p = _write(tmp_path, [_row("BTC/USD", 1.0, 100.0, 99.0, -1.0, 0.5)])
    rc = az.main(["--journal", str(p), "--out-dir", str(tmp_path)])
    assert rc == 0
    out = tmp_path / "p2_044h_live_journal_diagnosis.json"
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["schema"] == "p2_044h_live_journal_diagnosis/v1"
