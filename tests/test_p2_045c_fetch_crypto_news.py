"""
tests/test_p2_045c_fetch_crypto_news.py — P2-045C tests (CryptoCompare, free).
Pure stdlib + pytest. No network (fetch_cryptocompare not called).
"""

from __future__ import annotations

import json
from pathlib import Path

import fetch_crypto_news as cn


def test_normalize_unix_timestamp_to_date():
    # 1704196800 = 2024-01-02 12:00:00 UTC
    raw = [{"published_on": 1704196800, "title": "BTC rallies", "body": "x", "categories": "BTC|Trading"}]
    rows = cn.normalize_cryptocompare(raw)
    assert rows[0]["date"] == "2024-01-02"
    assert rows[0]["symbol"] == "BTC/USD"
    assert rows[0]["headline"] == "BTC rallies"


def test_non_coin_categories_filtered_out():
    raw = [{"published_on": 1704196800, "title": "t", "categories": "Trading|Market|Regulation"}]
    rows = cn.normalize_cryptocompare(raw)
    # no real coin tokens -> emitted once with empty symbol, not as "TRADING/USD"
    assert rows[0]["symbol"] == ""


def test_wanted_filter_restricts_symbols():
    raw = [{"published_on": 1704196800, "title": "t", "categories": "BTC|ETH|SOL"}]
    rows = cn.normalize_cryptocompare(raw, wanted=["BTC", "ETH"])
    assert {r["symbol"] for r in rows} == {"BTC/USD", "ETH/USD"}


def test_multi_coin_explodes_unique():
    raw = [{"published_on": 1704196800, "title": "t", "categories": "BTC|BTC|ETH"}]
    rows = cn.normalize_cryptocompare(raw)
    assert sorted(r["symbol"] for r in rows) == ["BTC/USD", "ETH/USD"]


def test_skips_without_timestamp():
    assert cn.normalize_cryptocompare([{"title": "no date"}]) == []


def test_write_roundtrip(tmp_path: Path):
    rows = cn.normalize_cryptocompare(
        [{"published_on": 1704196800, "title": "h", "categories": "BTC"}])
    out = tmp_path / "cn.jsonl"
    cn.write_jsonl(rows, out)
    back = [json.loads(l) for l in out.read_text().splitlines()]
    assert back[0]["symbol"] == "BTC/USD"
    assert back[0]["date"] == "2024-01-02"
