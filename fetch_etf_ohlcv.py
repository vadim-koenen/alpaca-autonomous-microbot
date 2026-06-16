#!/usr/bin/env python3
"""
fetch_etf_ohlcv.py — P2-044E daily OHLCV fetcher + normalizer for the equities
swing gate. RUN THIS ON THE MAC (it needs network). It writes the exact CSV
schema the gates expect: date,open,high,low,close,volume.

Why: the P2-044B/C/D gates are data-agnostic and need REAL daily bars. Claude
could not fetch market data in-session (web access restricted). This script is
the data bridge for the Mac.

Sources (explicit market data, per project strategy rules):
- yfinance (default convenience source): `pip install yfinance`
- Alpaca historical bars (preferred, read-only) — see note in main(); your repo
  already has Alpaca credentials in .env. This script keeps the dependency light
  and defaults to yfinance; swap in Alpaca if you prefer a single data vendor.

The normalization core (normalize_rows) is pure and unit-tested offline.
No broker orders, no trading, read-only data only.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REQUIRED = ["date", "open", "high", "low", "close", "volume"]

# Map common header variants (yfinance, Alpaca, Stooq, generic) -> canonical.
_ALIASES = {
    "date": "date", "datetime": "date", "timestamp": "date", "time": "date", "t": "date",
    "open": "open", "o": "open",
    "high": "high", "h": "high",
    "low": "low", "l": "low",
    "close": "close", "c": "close", "adj close": "close", "adjclose": "close",
    "volume": "volume", "v": "volume", "vol": "volume",
}


def _canon(key: str) -> Optional[str]:
    return _ALIASES.get((key or "").strip().lower())


def normalize_rows(raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure: map arbitrary OHLCV dict rows to the canonical schema. Prefers a true
    'close' over 'adj close' when both are present. Raises on missing OHLC."""
    out: List[Dict[str, Any]] = []
    for row in raw_rows:
        canon: Dict[str, Any] = {}
        has_true_close = any((k or "").strip().lower() == "close" for k in row)
        for k, val in row.items():
            c = _canon(k)
            if c is None:
                continue
            # Don't let 'adj close' overwrite a real 'close'.
            if c == "close" and (k or "").strip().lower() == "adj close" and has_true_close:
                continue
            canon[c] = val
        missing = [c for c in ("date", "open", "high", "low", "close") if c not in canon]
        if missing:
            raise KeyError(f"row missing required columns {missing}: {row}")
        canon.setdefault("volume", 0)
        # Coerce numerics; keep date as string.
        for c in ("open", "high", "low", "close", "volume"):
            canon[c] = float(canon[c])
        canon["date"] = str(canon["date"])[:10]
        out.append({c: canon[c] for c in REQUIRED})
    return out


def write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REQUIRED)
        w.writeheader()
        w.writerows(rows)


def fetch_yfinance(symbol: str, period: str, interval: str = "1d") -> List[Dict[str, Any]]:
    """Network call — Mac only. Returns raw row dicts for normalize_rows()."""
    try:
        import yfinance  # noqa: WPS433 (import inside function is intentional)
    except ImportError:
        raise SystemExit(
            "yfinance not installed. On the Mac run:  pip install yfinance\n"
            "Or supply your own CSV (date,open,high,low,close,volume) and skip this script."
        )
    df = yfinance.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise SystemExit(f"no data returned for {symbol}")
    df = df.reset_index()
    # Flatten any MultiIndex columns yfinance may return.
    df.columns = [(" ".join(map(str, c)).strip() if isinstance(c, tuple) else str(c)) for c in df.columns]
    return df.to_dict(orient="records")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch + normalize daily ETF OHLCV (Mac-side)")
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--period", default="10y", help="yfinance period, e.g. 10y, 5y, max")
    p.add_argument("--out", default="SPY_daily.csv")
    args = p.parse_args(argv)

    raw = fetch_yfinance(args.symbol, args.period)
    rows = normalize_rows(raw)
    write_csv(rows, Path(args.out))
    print(f"[fetch] wrote {len(rows)} rows to {args.out} for {args.symbol}")
    print(f"[fetch] next: python3 run_pivot_gate.py --csv {args.out} --print")
    return 0


if __name__ == "__main__":
    sys.exit(main())
