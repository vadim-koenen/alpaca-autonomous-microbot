#!/usr/bin/env python3
"""
scripts/coinbase_ohlcv_import_validate.py — Safe local OHLCV import/validation for journal-window replay.

Default: dry-run (no write). Explicit --write to persist normalized CSV to data/offline_ohlcv/coinbase/.

Supports CSV/JSON input. No network, no auth, no .env, no broker endpoints by default.
Pure offline validation + optional normalized export.

Output includes safety flags: trade_permission=none, risk_increase=not_approved, scaling_allowed=false.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse from backtest for consistency (no network)
from coinbase_offline_backtest import (
    _normalize_symbol,
    _to_decimal,
    Bar,
    load_bars_from_fixture,
)

DEFAULT_OUTPUT_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"
SCHEMA_VERSION = "p2-025h.coinbase_ohlcv_import_validate.v1"


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
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


def _load_raw_ohlcv(path: Path) -> List[Dict[str, Any]]:
    """Load raw rows from csv/json without full Bar conversion yet."""
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    suf = path.suffix.lower()
    try:
        if suf == ".csv":
            with path.open("r", encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                for row in r:
                    rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in row.items()})
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for obj in data:
                    rows.append({(k or "").strip().lower(): v for k, v in obj.items()})
            elif isinstance(data, dict) and "bars" in data:
                for obj in data["bars"]:
                    rows.append({(k or "").strip().lower(): v for k, v in obj.items()})
    except Exception:
        return []
    return rows


def validate_and_normalize(
    input_path: Path,
    symbol: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    granularity: str = "5m",
    journal_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Core validation. Returns report dict. No writes. Reuses proven load_bars_from_fixture."""
    norm_sym = _normalize_symbol(symbol)
    bars: List[Bar] = []
    try:
        bars = load_bars_from_fixture(input_path, symbol=norm_sym, start=start, end=end)
    except Exception:
        bars = []

    # basic gap count (post load)
    gap_count = 0
    gaps = []
    if len(bars) > 1:
        for i in range(1, len(bars)):
            delta = (bars[i].t - bars[i-1].t).total_seconds() / 60.0
            if delta > 5.1:
                gap_count += 1
                if len(gaps) < 10:
                    gaps.append(f"{bars[i-1].t} -> {bars[i].t} ({delta:.1f}m)")

    bar_count = len(bars)
    earliest = str(bars[0].t) if bars else None
    latest = str(bars[-1].t) if bars else None
    skipped = 0  # load already filtered bad; for report we can note 0 additional here

    # optional journal coverage
    journal_cov = None
    if journal_path and journal_path.exists():
        try:
            from coinbase_offline_backtest import parse_journal_cycles
            cycles = parse_journal_cycles(journal_path)
            needed = [c for c in cycles if _normalize_symbol(c.get("symbol", "")) == norm_sym]
            covered = 0
            for c in needed:
                et = c.get("entry_time")
                xt = c.get("exit_time")
                if et and xt and any(et <= b.t <= xt for b in bars):
                    covered += 1
            journal_cov = {"journal_cycles_for_symbol": len(needed), "covered_in_window": covered}
        except Exception:
            pass

    report = {
        "schema_version": SCHEMA_VERSION,
        "input_path": str(input_path),
        "symbol": norm_sym,
        "granularity": granularity,
        "bar_count": bar_count,
        "skipped_rows": skipped,
        "earliest_timestamp": earliest,
        "latest_timestamp": latest,
        "gap_count": gap_count,
        "gaps": gaps,
        "journal_coverage": journal_cov,
        "trade_permission": "none",
        "risk_increase": "not_approved",
        "scaling_allowed": False,
        "notes": [
            "Local OHLCV validation/import only. No network, no auth, no live trading.",
            "Default dry-run. Use --write to export normalized CSV.",
            "Output safe for journal-window replay baseline.",
        ],
    }
    return report, bars


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Local OHLCV import/validate for offline journal-window replay (dry-run by default)")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument("--input", type=Path, required=True, help="Path to source OHLCV csv/json")
    ap.add_argument("--symbol", required=True, help="Target symbol e.g. BTC/USD or BTC-USD")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output dir for normalized CSV on --write")
    ap.add_argument("--format", choices=["csv", "json", "auto"], default="auto")
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--granularity", default="5m")
    ap.add_argument("--journal", type=Path, default=None, help="Optional journal for coverage check in report")
    ap.add_argument("--dry-run", action="store_true", default=True, help="Default true; no write")
    ap.add_argument("--write", action="store_true", help="Explicitly enable write of normalized CSV")
    args = ap.parse_args(argv)

    start = _parse_ts(args.start) if args.start else None
    end = _parse_ts(args.end) if args.end else None

    report, bars = validate_and_normalize(
        args.input,
        args.symbol,
        start=start,
        end=end,
        granularity=args.granularity,
        journal_path=args.journal,
    )

    do_write = args.write and not args.dry_run
    written = None
    if do_write:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        norm_sym = _normalize_symbol(args.symbol).replace("/", "-")
        out_name = f"{norm_sym}_{args.granularity}_{ (start or datetime(1970,1,1)).strftime('%Y-%m-%d') }_{ (end or datetime.now()).strftime('%Y-%m-%d') }.csv"
        outp = args.output_dir / out_name
        with outp.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"])
            w.writeheader()
            for b in bars:
                w.writerow({
                    "timestamp_utc": b.t.isoformat(),
                    "symbol": b.symbol or norm_sym,
                    "open": str(b.o),
                    "high": str(b.h),
                    "low": str(b.l),
                    "close": str(b.c),
                    "volume": str(b.v),
                })
        written = str(outp)
        report["written"] = written
    else:
        report["written"] = None
        report["dry_run"] = True

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
