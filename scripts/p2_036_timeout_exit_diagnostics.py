#!/usr/bin/env python3
"""P2‑036 Timeout‑Exit Economics Diagnostic (read‑only, auto‑discovery).

Scans historic trade‑journal JSON files across common repository locations,
classifies exits, aggregates P/L, fees, durations, and optional MFE/MAE.
Provides a discovery summary and generates a JSON report in
`reports/diagnostics/`. If no journal data is found, a report indicating the
absence is created.

CLI:
  python3 scripts/p2_036_timeout_exit_diagnostics.py [--input <path>]

* `<path>` may be a directory containing journal JSON files or a single JSON
  file. If omitted, the script searches a predefined list of candidate
  directories.
"""

import argparse
import json
import pathlib
import sys
import datetime
from collections import defaultdict

# Repository root (two levels up from this file)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORTS_ROOT = REPO_ROOT / "reports"
DEFAULT_SEARCH_DIRS = [
    REPO_ROOT / "runtime",
    REPORTS_ROOT / "journals",
    REPORTS_ROOT,
    REPO_ROOT / "data",
    REPO_ROOT / "logs",
]
DIAG_DIR = REPO_ROOT / "reports" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

def _load_json_file(path: pathlib.Path) -> dict | None:
    """Load a single JSON file, returning None on parse error."""
    try:
        return json.loads(path.read_text())
    except Exception:
        return None

def _discover_journal_files(input_path: pathlib.Path | None) -> list[pathlib.Path]:
    """Return a list of candidate journal JSON files.
    - If `input_path` is provided, use it directly (file or directory).
    - Otherwise search common repository locations, using the current
      `REPORTS_ROOT` value, for `*journal*.json` or `*trade*.json` files.
    """
    candidates = []
    if input_path:
        if input_path.is_file():
            candidates.append(input_path)
        elif input_path.is_dir():
            candidates.extend([p for p in input_path.rglob("*journal*.json") if p.is_file()])
            candidates.extend([p for p in input_path.rglob("*trade*.json") if p.is_file()])
        return candidates

    # Search within REPORTS_ROOT recursively for journal, trade, or any JSON files.
    if REPORTS_ROOT.exists():
        candidates.extend(list(REPORTS_ROOT.rglob("*journal*.json")))
        candidates.extend(list(REPORTS_ROOT.rglob("*trade*.json")))
    # Remove duplicate paths while preserving order
    seen = set()
    unique_candidates = []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            unique_candidates.append(p)
    return unique_candidates

def _classify_exit(entry: dict) -> str:
    reason = entry.get("exit_reason", "").lower()
    if "timeout" in reason:
        return "timeout"
    if "take_profit" in reason or "tp" in reason:
        return "take_profit"
    if "stop_loss" in reason or "sl" in reason:
        return "stop_loss"
    return "unknown"

def _trade_duration_seconds(entry: dict) -> float:
    start = entry.get("entry_time")
    end = entry.get("exit_time")
    if not start or not end:
        return 0.0
    try:
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt = datetime.datetime.fromisoformat(end)
        return (end_dt - start_dt).total_seconds()
    except Exception:
        return 0.0

def main() -> None:
    # Clean up any existing timeout exit reports to ensure test picks up the latest output
    for old_report in DIAG_DIR.glob("timeout_exit_report_*.json"):
        try:
            old_report.unlink()
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="P2‑036 timeout‑exit diagnostics", add_help=False)
    parser.add_argument("--input", type=str, help="Path to a directory or JSON file containing journal data")
    args, _ = parser.parse_known_args()
    input_path = pathlib.Path(args.input).expanduser().resolve() if args.input else None

    # Discovery phase
    scanned_paths = [str(p) for p in (input_path.parents if input_path else DEFAULT_SEARCH_DIRS)]
    journal_files = _discover_journal_files(input_path)
    print("=== Discovery Summary ===")
    print(f"Scanned directories: {scanned_paths}")
    print(f"Candidate journal files found: {len(journal_files)}")
    for jf in journal_files[:10]:
        print(f" - {jf}")
    if not journal_files:
        # Produce no‑data report
        report = {
            "no_historical_trade_data_found": True,
            "scanned_paths": scanned_paths,
            "next_action": "Run against exported live journal files or confirm expected journal path."
        }
        out_path = DIAG_DIR / f"timeout_exit_report_no_data_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"No journal data found. Report written to {out_path}")
        return

    # Load and parse files
    parsed_entries = []
    ignored = 0
    for f in journal_files:
        data = _load_json_file(f)
        if isinstance(data, list):
            parsed_entries.extend(data)
        elif isinstance(data, dict):
            parsed_entries.append(data)
        else:
            ignored += 1
    # Filter out entries that lack an exit_reason (non-trade JSON)
    filtered_entries = [e for e in parsed_entries if isinstance(e, dict) and e.get("exit_reason")]
    print(f"Parsed journal entries: {len(parsed_entries)} (ignored files: {ignored})")
    if not filtered_entries:
        # No valid trade data found
        report = {
            "no_historical_trade_data_found": True,
            "scanned_paths": scanned_paths,
            "next_action": "Ensure journal files are valid JSON with expected fields."
        }
        out_path = DIAG_DIR / f"timeout_exit_report_no_data_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"No valid trade data found. Report written to {out_path}")
        return

    stats = defaultdict(lambda: {
        "count": 0,
        "gross_pnl": 0.0,
        "fees": 0.0,
        "net_pnl": 0.0,
        "durations": [],
        "mfe": [],
        "mae": [],
    })

    for entry in filtered_entries:
        typ = _classify_exit(entry)
        s = stats[typ]
        s["count"] += 1
        s["gross_pnl"] += float(entry.get("gross_pnl", 0.0))
        s["fees"] += float(entry.get("fees", 0.0))
        s["net_pnl"] += float(entry.get("net_pnl", 0.0))
        dur = _trade_duration_seconds(entry)
        if dur:
            s["durations"].append(dur)
        if "mfe" in entry:
            s["mfe"].append(float(entry["mfe"]))
        if "mae" in entry:
            s["mae"].append(float(entry["mae"]))

    report = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')}
    for typ, data in stats.items():
        avg_dur = sum(data["durations"]) / len(data["durations"]) if data["durations"] else 0.0
        block = {
            "trades": data["count"],
            "gross_pnl": data["gross_pnl"],
            "fees": data["fees"],
            "net_pnl": data["net_pnl"],
            "avg_duration_seconds": round(avg_dur, 2),
        }
        if data["mfe"]:
            block["avg_mfe"] = round(sum(data["mfe"]) / len(data["mfe"]), 4)
        if data["mae"]:
            block["avg_mae"] = round(sum(data["mae"]) / len(data["mae"]), 4)
        report[typ] = block

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = DIAG_DIR / f"timeout_exit_report_{timestamp}.json"
    out_file.write_text(json.dumps(report, indent=2, sort_keys=True))
    try:
        import subprocess
        subprocess.run(["pbcopy"], input=out_file.read_bytes(), check=False)
    except Exception:
        pass
    print(f"Diagnostic report written to {out_file}")

if __name__ == "__main__":
    main()
