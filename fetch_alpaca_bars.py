#!/usr/bin/env python3
"""
fetch_alpaca_bars.py — P2-044F Alpaca-native daily OHLCV fetcher for the swing
gate. RUN ON THE MAC (needs network + your Alpaca keys). Uses the SAME vendor as
execution, satisfying the project rule "Use Alpaca API only".

It reads ALPACA_API_KEY / ALPACA_SECRET_KEY from the environment (or .env) and
writes the canonical CSV schema the gates consume: date,open,high,low,close,volume.

GOVERNANCE
- Read-only MARKET DATA only. No orders, no trading, no runtime mutation.
- Never prints or logs API keys.
- Daily bars via Alpaca's free IEX feed by default (sufficient for daily-swing
  backtests). Pass --feed sip only if you have the paid SIP subscription.

Data tiers (FYI):
- Crypto bars: free, no subscription.
- Equity bars: free IEX feed is fine for daily backtests. SIP (full consolidated
  tape, ~Algo Trader Plus) is only needed for full-depth/real-time — not for this.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse the tested normalizer + writer from the yfinance fetcher.
from fetch_etf_ohlcv import normalize_rows, write_csv, REQUIRED  # noqa: F401


def load_keys(env_path: str = ".env") -> Dict[str, str]:
    """Read Alpaca keys from the environment, falling back to a .env file.
    Returns the keys WITHOUT printing them. Raises if missing."""
    key = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if (not key or not secret) and Path(env_path).exists():
        for line in Path(env_path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "ALPACA_API_KEY" and not key:
                key = v
            elif k == "ALPACA_SECRET_KEY" and not secret:
                secret = v
    if not key or not secret:
        raise SystemExit(
            "Missing ALPACA_API_KEY / ALPACA_SECRET_KEY. Set them in the environment "
            "or .env. (Paper keys also grant market-data access.)"
        )
    return {"key": key, "secret": secret}


def is_crypto_symbol(symbol: str) -> bool:
    """Crypto pairs look like BTC/USD, ETH/USD, SOL/USD. Equities are plain tickers."""
    return "/" in symbol


def _df_to_records(df, what: str) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        raise SystemExit(f"no bars returned for {what}")
    df = df.reset_index()
    df.columns = [str(c) for c in df.columns]
    return df.to_dict(orient="records")


def fetch_crypto_daily(symbol: str, years: int) -> List[Dict[str, Any]]:
    """Crypto daily bars — Mac only. Alpaca crypto market data is public (no keys needed)."""
    try:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError:
        raise SystemExit("alpaca-py not installed. On the Mac: pip install 'alpaca-py>=0.26'")
    client = CryptoHistoricalDataClient()  # crypto data needs no auth
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(years * 365.25))
    req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start, end=end)
    return _df_to_records(client.get_crypto_bars(req).df, f"{symbol} (crypto)")


def fetch_stock_daily(symbol: str, years: int, feed: str = "iex") -> List[Dict[str, Any]]:
    """Equity daily bars — Mac only. Uses your Alpaca keys; free IEX feed by default."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError:
        raise SystemExit("alpaca-py not installed. On the Mac: pip install 'alpaca-py>=0.26'")
    keys = load_keys()
    client = StockHistoricalDataClient(keys["key"], keys["secret"])
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(years * 365.25))
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                           start=start, end=end, feed=feed)
    return _df_to_records(client.get_stock_bars(req).df, f"{symbol} (feed={feed})")


def fetch_daily(symbol: str, years: int, feed: str = "iex") -> List[Dict[str, Any]]:
    """Dispatch to the right Alpaca client based on the symbol (crypto vs equity).
    THIS is the correct entry point for a crypto bot: BTC/USD -> crypto client."""
    if is_crypto_symbol(symbol):
        return fetch_crypto_daily(symbol, years)
    return fetch_stock_daily(symbol, years, feed)


# Back-compat alias.
fetch_alpaca_daily = fetch_stock_daily


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch daily OHLCV from Alpaca (Mac-side). "
                                            "Crypto (BTC/USD) and equity (SPY) auto-detected.")
    p.add_argument("--symbol", default="BTC/USD", help="e.g. BTC/USD (crypto) or SPY (equity)")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--feed", default="iex", choices=["iex", "sip"], help="equity feed only")
    p.add_argument("--out", default="bars_daily.csv")
    args = p.parse_args(argv)

    raw = fetch_daily(args.symbol, args.years, args.feed)
    rows = normalize_rows(raw)
    write_csv(rows, Path(args.out))
    kind = "crypto" if is_crypto_symbol(args.symbol) else f"equity feed={args.feed}"
    print(f"[alpaca-fetch] wrote {len(rows)} daily bars to {args.out} for {args.symbol} ({kind})")
    print(f"[alpaca-fetch] next: python3 news_edge_research.py --prices {args.out} --news news.jsonl --print")
    return 0


if __name__ == "__main__":
    sys.exit(main())
