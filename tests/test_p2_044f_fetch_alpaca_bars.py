"""
tests/test_p2_044f_fetch_alpaca_bars.py — P2-044F tests.
Pure stdlib + pytest. No network, no real Alpaca SDK call. Deterministic.
"""

from __future__ import annotations

import pytest

import fetch_alpaca_bars as fa


def test_load_keys_from_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "PKTEST")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "SECRET")
    keys = fa.load_keys()
    assert keys == {"key": "PKTEST", "secret": "SECRET"}


def test_load_keys_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text('ALPACA_API_KEY="PKFILE"\nALPACA_SECRET_KEY=SECFILE\nBROKER=alpaca\n')
    keys = fa.load_keys(str(env))
    assert keys["key"] == "PKFILE"
    assert keys["secret"] == "SECFILE"


def test_load_keys_missing_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(SystemExit):
        fa.load_keys(str(tmp_path / "nope.env"))


def test_is_crypto_symbol_routing():
    assert fa.is_crypto_symbol("BTC/USD") is True
    assert fa.is_crypto_symbol("ETH/USD") is True
    assert fa.is_crypto_symbol("SPY") is False
    assert fa.is_crypto_symbol("AAPL") is False


def test_fetch_daily_dispatches_on_symbol(monkeypatch):
    calls = {}
    monkeypatch.setattr(fa, "fetch_crypto_daily", lambda s, y: calls.setdefault("crypto", (s, y)) or [])
    monkeypatch.setattr(fa, "fetch_stock_daily",
                        lambda s, y, feed="iex", adjustment="raw": calls.setdefault("stock", (s, y)) or [])
    fa.fetch_daily("BTC/USD", 3)
    fa.fetch_daily("SPY", 3)
    assert calls["crypto"] == ("BTC/USD", 3)
    assert calls["stock"] == ("SPY", 3)


def test_alpaca_records_normalize_to_schema():
    # Shape mirrors df.reset_index().to_dict('records') from alpaca-py daily bars.
    raw = [{"symbol": "SPY", "timestamp": "2024-01-02 05:00:00+00:00",
            "open": 470.0, "high": 472.0, "low": 469.0, "close": 471.5,
            "volume": 1234567, "trade_count": 1000, "vwap": 471.0}]
    rows = fa.normalize_rows(raw)
    assert rows[0]["date"] == "2024-01-02"
    assert rows[0]["close"] == pytest.approx(471.5)
    assert list(rows[0].keys()) == fa.REQUIRED
