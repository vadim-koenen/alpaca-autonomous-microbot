"""
tests/test_p2_044e_fetch_etf_ohlcv.py — P2-044E normalizer tests.
Pure stdlib + pytest. No network (fetch_yfinance is not called here).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import fetch_etf_ohlcv as fx


def test_normalize_yfinance_style_headers():
    raw = [{"Date": "2024-01-02", "Open": 100.0, "High": 101.0, "Low": 99.0,
            "Close": 100.5, "Adj Close": 100.4, "Volume": 1000000}]
    rows = fx.normalize_rows(raw)
    assert rows[0] == {"date": "2024-01-02", "open": 100.0, "high": 101.0,
                       "low": 99.0, "close": 100.5, "volume": 1000000.0}


def test_adj_close_does_not_override_true_close():
    raw = [{"Date": "2024-01-02", "Open": 1, "High": 2, "Low": 0.5,
            "Close": 1.5, "Adj Close": 9.9, "Volume": 10}]
    assert fx.normalize_rows(raw)[0]["close"] == pytest.approx(1.5)


def test_adj_close_used_when_no_true_close():
    raw = [{"date": "2024-01-02", "open": 1, "high": 2, "low": 0.5,
            "adjclose": 1.7, "volume": 10}]
    assert fx.normalize_rows(raw)[0]["close"] == pytest.approx(1.7)


def test_short_header_aliases():
    raw = [{"t": "2024-01-02T00:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 7}]
    out = fx.normalize_rows(raw)[0]
    assert out["date"] == "2024-01-02"  # truncated to 10 chars
    assert out["close"] == pytest.approx(1.5)
    assert out["volume"] == pytest.approx(7.0)


def test_missing_required_raises():
    with pytest.raises(KeyError):
        fx.normalize_rows([{"Date": "2024-01-02", "Open": 1, "High": 2, "Low": 0.5}])  # no close


def test_volume_defaults_to_zero():
    raw = [{"date": "2024-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    assert fx.normalize_rows(raw)[0]["volume"] == 0.0


def test_write_csv_roundtrip(tmp_path: Path):
    rows = fx.normalize_rows([{"Date": "2024-01-02", "Open": 1, "High": 2,
                               "Low": 0.5, "Close": 1.5, "Volume": 10}])
    out = tmp_path / "x.csv"
    fx.write_csv(rows, out)
    with out.open() as f:
        back = list(csv.DictReader(f))
    assert back[0]["date"] == "2024-01-02"
    assert float(back[0]["close"]) == pytest.approx(1.5)
    assert list(back[0].keys()) == fx.REQUIRED
