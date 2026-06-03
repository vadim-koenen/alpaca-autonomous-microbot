#!/usr/bin/env python3
"""
scripts/coinbase_ohlcv_acquisition_plan.py — Planning tool for populating local OHLCV files
for journal-window replay coverage.

Reads journal (EXIT cycles), derives exact required symbols + [earliest_entry, latest_exit] window,
recommends conventional filenames under data/offline_ohlcv/coinbase/,
detects which are missing, emits exact validation+write commands for manual placement,
and a JSON report with network_enabled=false (manual by default), safety flags.

Optional public fetcher (coinbase_public_ohlcv_fetch.py) can be used for opt-in unauth market data
if present; plan remains network-free and recommends manual + validate workflow.

Pure offline. No auth, no .env, no broker, no network by default (plan never fetches).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import parse_journal_cycles, _normalize_symbol

DEFAULT_JOURNAL = ROOT / "journal_coinbase_crypto.csv"
DATA_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"
SCHEMA_VERSION = "p2-025i.coinbase_ohlcv_acquisition_plan.v1"
DEFAULT_GRANULARITY = "5m"


def _fmt_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "1970-01-01"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _recommended_filename(symbol: str, granularity: str, start: Optional[datetime], end: Optional[datetime]) -> str:
    fsym = _normalize_symbol(symbol).replace("/", "-")
    s = _fmt_date(start)
    e = _fmt_date(end)
    return f"{fsym}_{granularity}_{s}_{e}.csv"


def build_acquisition_plan(
    *,
    journal_path: Optional[Path] = None,
    granularity: str = DEFAULT_GRANULARITY,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    cycles = parse_journal_cycles(jpath)

    needed: set[str] = set()
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None
    for c in cycles:
        sym = _normalize_symbol(c.get("symbol", ""))
        if sym:
            needed.add(sym)
        et = c.get("entry_time")
        xt = c.get("exit_time")
        if et and (earliest is None or et < earliest):
            earliest = et
        if xt and (latest is None or xt > latest):
            latest = xt

    odir = Path(output_dir) if output_dir else DATA_DIR

    expected_files: List[str] = []
    for sym in sorted(needed):
        expected_files.append(_recommended_filename(sym, granularity, earliest, latest))

    # detect missing (best effort; does not create dir)
    missing_files: List[str] = []
    present: set[str] = set()
    if odir.exists():
        for f in list(odir.glob("*.csv")) + list(odir.glob("*.json")):
            present.add(f.name)
    for ef in expected_files:
        if ef not in present:
            missing_files.append(ef)

    # recommended commands (manual path: user supplies source CSV/JSON from exchange export / public source)
    commands: List[Dict[str, str]] = []
    for sym in sorted(needed):
        fn = _recommended_filename(sym, granularity, earliest, latest)
        placeholder = f"/path/to/your-{sym.replace('/', '-').lower()}.csv"
        cmd = (
            f"python3 scripts/coinbase_ohlcv_import_validate.py --json "
            f"--input {placeholder} --symbol {sym} --write --output-dir {odir}"
        )
        commands.append({
            "symbol": sym,
            "recommended_filename": fn,
            "validate_import_cmd": cmd,
        })

    # optional fetcher hint if script present on disk (never executes here)
    fetcher_path = ROOT / "scripts" / "coinbase_public_ohlcv_fetch.py"
    fetcher_hint: Optional[str] = None
    if fetcher_path.exists():
        ex = _fmt_date(earliest)
        ey = _fmt_date(latest)
        fetcher_hint = (
            f"python3 scripts/coinbase_public_ohlcv_fetch.py --symbol {sorted(needed)[0] if needed else 'BTC/USD'} "
            f"--start {ex} --end {ey} --granularity {granularity} --fetch --write"
        )

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "journal_path": str(jpath),
        "required_symbols": sorted(list(needed)),
        "start": str(earliest) if earliest else None,
        "end": str(latest) if latest else None,
        "granularity": granularity,
        "output_dir": str(odir),
        "expected_files": expected_files,
        "missing_files": sorted(missing_files),
        "acquisition_mode": "manual_by_default",
        "network_enabled": False,
        "trade_permission": "none",
        "risk_increase": "not_approved",
        "scaling_allowed": False,
        "recommended_commands": commands,
        "notes": [
            "Acquisition planning only. No network performed by this script.",
            "Manual workflow (default): export OHLCV for the symbols/windows from public exchange UI or other source as CSV/JSON.",
            "Then run the listed validate --write commands (dry-run first without --write).",
            "Place files (or let --write emit) under data/offline_ohlcv/coinbase/ for auto-discovery by journal replay.",
            "If coinbase_public_ohlcv_fetch.py is present, it provides opt-in unauthenticated public market-data fetch (see its --help).",
            "After files are in place, run: python3 scripts/coinbase_journal_window_replay_report.py --json",
            "Do not commit large real OHLCV data files to the repo unless explicitly approved.",
            "This workflow and all tools are offline-only: trade_permission=none, no live trading, no auth, no .env, no restart.",
        ],
    }
    if fetcher_hint:
        report["public_fetcher_hint"] = fetcher_hint
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="OHLCV acquisition plan for journal-window replay (manual by default, no network)")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument("--journal", type=Path, default=None, help="Path to journal csv (default journal_coinbase_crypto.csv)")
    ap.add_argument("--granularity", default=DEFAULT_GRANULARITY)
    ap.add_argument("--output-dir", type=Path, default=None, help="Target data dir (default data/offline_ohlcv/coinbase)")
    args = ap.parse_args(argv)

    report = build_acquisition_plan(
        journal_path=args.journal,
        granularity=args.granularity,
        output_dir=args.output_dir,
    )

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
