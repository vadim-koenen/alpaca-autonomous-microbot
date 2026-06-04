#!/usr/bin/env python3
"""
scripts/coinbase_public_ohlcv_fetch.py — Opt-in public unauthenticated OHLCV fetcher
for manual acquisition workflow (P2-025I).

Uses ONLY public market-data endpoint (https://api.exchange.coinbase.com/products/.../candles).
No authentication, no API keys, no .env, no secrets, no broker/trading clients, no Advanced Trade endpoints.

Exchange public candles is preferred over Advanced Trade public candles when no auth is allowed
because the legacy Exchange /products/{id}/candles endpoint provides historical 5m (and other) candles
without requiring API keys or authenticated requests (Advanced Trade historical often needs auth or has
different access rules for full history).

Default: dry-run (no network, no write). Explicit --fetch to perform public request.
Explicit --write to persist normalized CSV to data/offline_ohlcv/coinbase/.

Supports chunked requests (299 bars/chunk max to respect Exchange 300-bar limit) with small throttle
between chunks for large windows (e.g. multi-day journal replay windows).

Intended for populating local files so journal-window replay can achieve coverage.
After fetch+write, re-run the journal replay report.

Network is DISABLED in tests (always mocked). This script does not approve live trading.
Always emits trade_permission=none / risk_increase=not_approved / scaling_allowed=false.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import _normalize_symbol

DEFAULT_OUTPUT_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"
SCHEMA_VERSION = "p2-025i.coinbase_public_ohlcv_fetch.v1"
PUBLIC_BASE = "https://api.exchange.coinbase.com"

# granularity seconds supported by the public candles API
GRAN_MAP: Dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _to_iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_exchange_candles_single(
    prod: str,
    start: datetime,
    end: datetime,
    gsec: int,
) -> List[Dict[str, Any]]:
    """Low-level single request to Exchange public candles. No auth ever."""
    siso = _to_iso_z(start)
    eiso = _to_iso_z(end)
    url = f"{PUBLIC_BASE}/products/{prod}/candles?granularity={gsec}&start={siso}&end={eiso}"
    # deliberately no Authorization / CB-ACCESS-KEY / any secret headers
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "coinbase-public-ohlcv-fetch/0.1 (market-data-only; no-auth)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"public fetch HTTP {e.code}: {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"public fetch error: {e}") from e

    bars: List[Dict[str, Any]] = []
    if not isinstance(data, list):
        return bars
    # Exchange response: list of [unix_time, low, high, open, close, volume] newest first
    for row in reversed(data):
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            ts = datetime.fromtimestamp(int(row[0]), tz=timezone.utc)
            bars.append({
                "timestamp_utc": ts.isoformat(),
                "open": str(row[3]),
                "high": str(row[2]),
                "low": str(row[1]),
                "close": str(row[4]),
                "volume": str(row[5]),
            })
        except Exception:
            continue
    return bars


def fetch_public_candles(
    symbol: str,
    start: datetime,
    end: datetime,
    granularity: str = "5m",
) -> List[Dict[str, Any]]:
    """Public unauth only. Chunked to respect Exchange max ~300 bars/request.
    Returns deduped, sorted list of normalized bar dicts. No auth ever sent.
    Uses 299-bar safe chunks + throttle between requests.
    """
    norm = _normalize_symbol(symbol)
    prod = norm.replace("/", "-")
    gsec = GRAN_MAP.get(granularity, 300)
    gran_td = timedelta(seconds=gsec)

    # Safe chunk: 299 bars max per request (Exchange limit is 300)
    max_bars_per_chunk = 299
    chunk_td = timedelta(seconds=gsec * max_bars_per_chunk)

    all_bars: List[Dict[str, Any]] = []
    seen: set = set()
    cur = start
    first = True
    while cur < end:
        ch_end = min(cur + chunk_td, end)
        try:
            chunk = _fetch_exchange_candles_single(prod, cur, ch_end, gsec)
            for b in chunk:
                ts = b["timestamp_utc"]
                if ts not in seen:
                    seen.add(ts)
                    b["symbol"] = norm  # ensure
                    all_bars.append(b)
        except Exception as e:
            # surface but continue? for robustness on partial windows; re-raise for now to match prior behavior
            raise
        cur = ch_end
        if cur < end:
            # small throttle to be polite to public API (no auth so rate limited)
            time.sleep(0.25)
    all_bars.sort(key=lambda b: b["timestamp_utc"])
    return all_bars


def _write_normalized_csv(bars: List[Dict[str, Any]], outp: Path) -> None:
    import csv
    outp.parent.mkdir(parents=True, exist_ok=True)
    with outp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for b in bars:
            w.writerow({
                "timestamp_utc": b["timestamp_utc"],
                "symbol": b["symbol"],
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": b.get("volume", "0"),
            })


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Opt-in public unauth OHLCV fetch (market data only) + normalize for journal replay")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument("--symbol", required=True, help="e.g. BTC/USD or BTC-USD")
    ap.add_argument("--start", required=True, help="Start YYYY-MM-DD[THH:MM:SSZ]")
    ap.add_argument("--end", required=True, help="End YYYY-MM-DD[THH:MM:SSZ]")
    ap.add_argument("--granularity", default="5m")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--fetch", action="store_true", default=False, help="Opt-in: perform the public unauthenticated fetch (default: no network)")
    ap.add_argument("--dry-run", action="store_true", default=True, help="Default true; no write")
    ap.add_argument("--write", action="store_true", help="Explicitly enable write of normalized CSV")
    args = ap.parse_args(argv)

    norm_sym = _normalize_symbol(args.symbol)
    start = _parse_ts(args.start)
    end = _parse_ts(args.end)
    if not start or not end:
        print("ERROR: invalid --start/--end", file=sys.stderr)
        return 2

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "symbol": norm_sym,
        "granularity": args.granularity,
        "start": str(start),
        "end": str(end),
        "output_dir": str(args.output_dir),
        "network_enabled": bool(args.fetch),
        "trade_permission": "none",
        "risk_increase": "not_approved",
        "scaling_allowed": False,
        "notes": [
            "Public market-data only via legacy exchange API. No auth, no keys, no .env, no brokerage endpoints.",
            "Opt-in with --fetch. Default is dry-run / no network.",
            "Use together with coinbase_ohlcv_import_validate.py or this tool's --write for normalized files.",
            "Output safe for journal-window replay. This does not approve live trading.",
        ],
    }

    bars: List[Dict[str, Any]] = []
    fetch_error: Optional[str] = None
    if args.fetch:
        try:
            bars = fetch_public_candles(norm_sym, start, end, granularity=args.granularity)
            report["fetched_bar_count"] = len(bars)
            report["earliest_fetched"] = bars[0]["timestamp_utc"] if bars else None
            report["latest_fetched"] = bars[-1]["timestamp_utc"] if bars else None
        except Exception as e:
            fetch_error = str(e)
            report["fetch_error"] = fetch_error
            bars = []

    # --write is explicit enable; default dry-run is advisory. --write takes precedence for action.
    do_write = bool(args.write) and not fetch_error
    if args.dry_run and not args.write:
        do_write = False
    written = None
    if do_write and bars:
        fsym = norm_sym.replace("/", "-")
        s = _fmt_date_for_name(start)
        e = _fmt_date_for_name(end)
        out_name = f"{fsym}_{args.granularity}_{s}_{e}.csv"
        outp = args.output_dir / out_name
        _write_normalized_csv(bars, outp)
        written = str(outp)
        report["written"] = written
    else:
        report["written"] = None
        if not args.fetch or not do_write:
            report["dry_run"] = True

    if fetch_error:
        report["notes"].append(f"Fetch failed (no secrets were sent): {fetch_error}")

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print(json.dumps(report, indent=2))
    return 0 if not fetch_error else 1


def _fmt_date_for_name(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d")


if __name__ == "__main__":
    sys.exit(main())
