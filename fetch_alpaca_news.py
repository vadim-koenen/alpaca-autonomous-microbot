#!/usr/bin/env python3
"""
fetch_alpaca_news.py — P2-045B Alpaca historical NEWS fetcher (Mac-side).

Pulls timestamped news headlines for symbols from Alpaca's news API (same vendor
as execution; your existing keys) and writes a JSONL the news-edge researcher
consumes: {date, symbol, headline, summary}. RUN ON THE MAC (needs network).

GOVERNANCE: read-only news data. No orders, no trading, no runtime mutation.
Never prints API keys. The normalizer is pure and unit-tested offline.

Pipeline:
  python3 fetch_alpaca_bars.py  --symbol BTC/USD --years 3 --out BTC_daily.csv   # (crypto via bars)
  python3 fetch_alpaca_news.py  --symbols BTC/USD,ETH/USD --years 3 --out news.jsonl
  python3 news_edge_research.py --prices BTC_daily.csv --news news.jsonl --print
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fetch_alpaca_bars import load_keys  # reuse env/.env key loading (never prints keys)


def normalize_news_records(raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure: map Alpaca news dicts to {date, symbol, headline, summary}. One row per
    (article, symbol). Unit-tested offline."""
    out: List[Dict[str, Any]] = []
    for r in raw_rows:
        ts = r.get("created_at") or r.get("updated_at") or r.get("date") or r.get("timestamp")
        if not ts:
            continue
        date = str(ts)[:10]
        headline = (r.get("headline") or r.get("title") or "").strip()
        summary = (r.get("summary") or "").strip()
        symbols = r.get("symbols") or r.get("symbol") or []
        if isinstance(symbols, str):
            symbols = [symbols]
        if not symbols:
            symbols = [""]
        for sym in symbols:
            out.append({"date": date, "symbol": str(sym).strip(),
                        "headline": headline, "summary": summary})
    return out


def write_jsonl(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def fetch_news(symbols: List[str], years: int) -> List[Dict[str, Any]]:
    """Network call — Mac only. Returns raw article dicts for normalize_news_records()."""
    try:
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest
    except ImportError:
        raise SystemExit("alpaca-py not installed or too old. On the Mac: pip install 'alpaca-py>=0.26'")

    keys = load_keys()
    client = NewsClient(keys["key"], keys["secret"])
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(years * 365.25))
    req = NewsRequest(symbols=",".join(symbols), start=start, end=end, include_content=False)
    news_set = client.get_news(req)
    # alpaca-py returns a NewsSet; .data["news"] is a list of News models.
    articles = getattr(news_set, "data", {}).get("news", []) if hasattr(news_set, "data") else []
    out: List[Dict[str, Any]] = []
    for a in articles:
        d = a.__dict__ if hasattr(a, "__dict__") else dict(a)
        out.append(d)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch Alpaca historical news (Mac-side)")
    p.add_argument("--symbols", default="BTC/USD,ETH/USD", help="Comma-separated symbols.")
    p.add_argument("--years", type=int, default=3)
    p.add_argument("--out", default="news.jsonl")
    args = p.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    raw = fetch_news(symbols, args.years)
    rows = normalize_news_records(raw)
    write_jsonl(rows, Path(args.out))
    print(f"[news-fetch] wrote {len(rows)} symbol-tagged headlines to {args.out}")
    print(f"[news-fetch] next: python3 news_edge_research.py --prices <bars.csv> --news {args.out} --print")
    return 0


if __name__ == "__main__":
    sys.exit(main())
