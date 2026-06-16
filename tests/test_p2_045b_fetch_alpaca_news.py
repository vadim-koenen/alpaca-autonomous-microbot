"""
tests/test_p2_045b_fetch_alpaca_news.py — P2-045B normalizer tests.
Pure stdlib + pytest. No network (fetch_news not called).
"""

from __future__ import annotations

import json
from pathlib import Path

import fetch_alpaca_news as fn


def test_normalize_explodes_multi_symbol_articles():
    raw = [{"created_at": "2024-01-02T13:00:00Z", "headline": "ETF approval",
            "summary": "big", "symbols": ["BTC/USD", "ETH/USD"]}]
    rows = fn.normalize_news_records(raw)
    assert len(rows) == 2
    assert {r["symbol"] for r in rows} == {"BTC/USD", "ETH/USD"}
    assert all(r["date"] == "2024-01-02" for r in rows)


def test_normalize_handles_single_symbol_and_title_alias():
    raw = [{"date": "2024-02-01", "title": "Rally", "symbol": "BTC/USD"}]
    rows = fn.normalize_news_records(raw)
    assert rows[0]["headline"] == "Rally"
    assert rows[0]["symbol"] == "BTC/USD"


def test_normalize_skips_rows_without_timestamp():
    raw = [{"headline": "no date"}]
    assert fn.normalize_news_records(raw) == []


def test_write_jsonl_roundtrip(tmp_path: Path):
    rows = fn.normalize_news_records(
        [{"created_at": "2024-01-02T00:00:00Z", "headline": "h", "symbols": ["BTC/USD"]}])
    out = tmp_path / "news.jsonl"
    fn.write_jsonl(rows, out)
    back = [json.loads(l) for l in out.read_text().splitlines()]
    assert back[0]["symbol"] == "BTC/USD"
    assert back[0]["date"] == "2024-01-02"
