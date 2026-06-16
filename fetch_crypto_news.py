#!/usr/bin/env python3
"""
fetch_crypto_news.py — P2-045C crypto-focused news fetcher (Mac-side, FREE).

Pulls CRYPTO headlines from CryptoCompare's news API — free, NO API KEY required —
and writes the JSONL the news-edge researcher consumes: {date, symbol, headline,
summary}. Pages backward in time via the `lTs` cursor for history depth.

RUN ON THE MAC / Claude Code (needs network). Read-only news; no orders, no
trading, no runtime mutation. The normalizer is pure and unit-tested offline.

Pipeline:
  python3 fetch_alpaca_bars.py  --symbol BTC/USD --years 5 --out BTC_daily.csv
  python3 fetch_crypto_news.py  --currencies BTC,ETH,SOL --pages 30 --out crypto_news.jsonl
  python3 news_edge_research.py --prices BTC_daily.csv --news crypto_news.jsonl --print

Note: free news APIs favor recent history. If news_edge_research returns
INSUFFICIENT_DATA, raise --pages, add currencies, or accept that deep multi-year
crypto news history generally requires a paid archive.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fetch_alpaca_news import write_jsonl  # reuse JSONL writer

API_URL = "https://min-api.cryptocompare.com/data/v2/news/"
# Non-coin category tokens CryptoCompare attaches that are NOT tradable symbols.
_NON_COIN = {"TRADING", "MARKET", "MINING", "REGULATION", "TECHNOLOGY", "BUSINESS",
             "ICO", "EXCHANGE", "WALLET", "ALTCOIN", "BLOCKCHAIN", "FIAT", "ASIA",
             "SPONSORED", "COMMODITY", "OTHER", "WEB3", "NFT", "DEFI"}


def _to_date(ts: Any) -> Optional[str]:
    if ts is None or ts == "":
        return None
    try:  # unix epoch seconds (CryptoCompare 'published_on')
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return str(ts)[:10]  # already an ISO string


def normalize_cryptocompare(articles: List[Dict[str, Any]],
                            wanted: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Pure: map CryptoCompare articles to {date, symbol, headline, summary}, one row
    per tagged coin. `wanted` (upper-case codes) filters which coins to emit."""
    wanted_set = {w.upper() for w in wanted} if wanted else None
    out: List[Dict[str, Any]] = []
    for a in articles:
        date = _to_date(a.get("published_on") or a.get("date") or a.get("published_at"))
        if not date:
            continue
        headline = (a.get("title") or a.get("headline") or "").strip()
        summary = (a.get("body") or a.get("summary") or "").strip()
        cats = a.get("categories") or ""
        tokens = [t.strip().upper() for t in str(cats).replace(",", "|").split("|") if t.strip()]
        codes = [t for t in tokens if t not in _NON_COIN]
        if wanted_set is not None:
            codes = [c for c in codes if c in wanted_set]
        if not codes:
            codes = [""]
        seen = set()
        for code in codes:
            if code in seen:
                continue
            seen.add(code)
            out.append({"date": date, "symbol": f"{code}/USD" if code else "",
                        "headline": headline, "summary": summary})
    return out


def fetch_cryptocompare(currencies: List[str], pages: int = 20) -> List[Dict[str, Any]]:
    """Network call — Mac only. Pages backward in time via lTs. No API key required."""
    import urllib.parse
    import urllib.request

    params = {"lang": "EN", "sortOrder": "latest"}
    if currencies:
        params["categories"] = ",".join(currencies)

    articles: List[Dict[str, Any]] = []
    l_ts: Optional[int] = None
    seen_ids = set()
    for _ in range(max(1, pages)):
        q = dict(params)
        if l_ts is not None:
            q["lTs"] = str(l_ts)
        url = API_URL + "?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        batch = data.get("Data") or []
        if not batch:
            break
        new = [a for a in batch if a.get("id") not in seen_ids]
        if not new:
            break
        for a in new:
            seen_ids.add(a.get("id"))
        articles.extend(new)
        oldest = min(int(a.get("published_on", 0)) for a in new if a.get("published_on"))
        l_ts = oldest - 1  # walk further back
    return articles


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch crypto news from CryptoCompare (free, Mac-side)")
    p.add_argument("--currencies", default="BTC,ETH,SOL", help="Comma-separated coin codes.")
    p.add_argument("--pages", type=int, default=20, help="History pages (~50 articles each).")
    p.add_argument("--out", default="crypto_news.jsonl")
    args = p.parse_args(argv)

    codes = [c.strip().upper() for c in args.currencies.split(",") if c.strip()]
    raw = fetch_cryptocompare(codes, pages=args.pages)
    rows = normalize_cryptocompare(raw, wanted=codes)
    write_jsonl(rows, Path(args.out))
    print(f"[crypto-news] wrote {len(rows)} symbol-tagged headlines to {args.out}")
    print(f"[crypto-news] next: python3 news_edge_research.py --prices <bars.csv> --news {args.out} --print")
    return 0


if __name__ == "__main__":
    sys.exit(main())
