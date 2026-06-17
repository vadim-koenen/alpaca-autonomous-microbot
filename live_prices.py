#!/usr/bin/env python3
"""
live_prices.py — P2-046O: live market prices from Alpaca (replaces stale CSV closes).

Pulls the latest trade price for the basket from Alpaca's market-data API (equities via the free
IEX feed, crypto in real time). Resilient by design: a short TTL cache avoids hammering the API on
rapid UI refreshes, and ANY failure (offline, missing keys, rate limit) falls back to the last CSV
close so the app never breaks.

GOVERNANCE: read-only market data. No orders. Keys (paper or live both grant data access) load from
`.env`, never printed, never committed.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from alpaca_paper_broker import CRYPTO_ROOTS, _read_keys
from planner_service import latest_prices_from_csvs


def _alpaca_fetch(symbols: List[str]) -> Dict[str, float]:
    """Fetch latest trade prices from Alpaca. Equities use account keys (IEX); crypto needs none."""
    out: Dict[str, float] = {}
    crypto = [s for s in symbols if s.upper() in CRYPTO_ROOTS]
    equities = [s for s in symbols if s.upper() not in CRYPTO_ROOTS]

    if equities:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest
        keys = _read_keys("ALPACA_API_KEY", "ALPACA_SECRET_KEY")
        client = StockHistoricalDataClient(keys["key"], keys["secret"])
        resp = client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=equities))
        for sym, trade in resp.items():
            out[sym.upper()] = float(trade.price)

    if crypto:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoLatestTradeRequest
        client = CryptoHistoricalDataClient()  # crypto market data needs no keys
        pairs = [f"{s.upper()}/USD" for s in crypto]
        resp = client.get_crypto_latest_trade(CryptoLatestTradeRequest(symbol_or_symbols=pairs))
        for pair, trade in resp.items():
            out[pair.split("/")[0].upper()] = float(trade.price)

    return out


class LivePriceProvider:
    """Callable price source: live Alpaca quotes with a TTL cache and CSV fallback."""

    def __init__(self, symbols: List[str], csv_map: Dict[str, str], *,
                 fetcher: Callable[[List[str]], Dict[str, float]] = _alpaca_fetch,
                 ttl_seconds: float = 20.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.symbols = list(symbols)
        self.csv_map = dict(csv_map)
        self._fetch = fetcher
        self.ttl = ttl_seconds
        self._clock = clock
        self._cache: Optional[Dict[str, float]] = None
        self._cached_at = -1e9
        self.last_source = "none"

    def _csv(self) -> Dict[str, float]:
        try:
            return latest_prices_from_csvs(self.csv_map)
        except Exception:
            return {}

    def __call__(self) -> Dict[str, float]:
        now = self._clock()
        if self._cache is not None and (now - self._cached_at) < self.ttl:
            return self._cache
        try:
            live = self._fetch(self.symbols) or {}
        except Exception:
            live = {}
        if live:
            # backfill any symbol the live feed didn't return with its last CSV close
            csv = self._csv()
            for s in self.symbols:
                if s.upper() not in {k.upper() for k in live} and s in csv:
                    live[s] = csv[s]
            self._cache, self._cached_at, self.last_source = live, now, "live"
            return live
        # total live failure -> CSV fallback (do not cache, so we retry next call)
        self.last_source = "csv_fallback"
        return self._csv()
