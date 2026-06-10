#!/usr/bin/env python3
"""P2-037 Journal Provenance and Export Diagnostic (Read-Only)

Searches local directories for `*journal*.csv` files, extracts closed trade
records by pairing `BUY` and `EXIT` log rows, and exports normalized JSON 
representations to `reports/journals/`.
"""

import csv
import json
import pathlib
import sys
import datetime
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORTS_ROOT = REPO_ROOT / "reports"
JOURNALS_DIR = REPORTS_ROOT / "journals"

def _infer_entry_time(exit_time_str: str, reason: str) -> str | None:
    if not exit_time_str or not reason:
        return None
    m = re.search(r'([\d\.]+)min held', reason)
    if m:
        try:
            mins = float(m.group(1))
            exit_dt = datetime.datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
            entry_dt = exit_dt - datetime.timedelta(minutes=mins)
            return entry_dt.isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    return None

def parse_journal_csv(csv_path: pathlib.Path) -> list[dict]:
    trades = []
    open_positions = {}
    
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = row.get("action", "").upper()
            decision = row.get("decision", "").upper()
            symbol = row.get("symbol", "")
            
            if action == "BUY" and decision == "PLACED" and symbol:
                open_positions[symbol] = {
                    "entry_time": row.get("timestamp"),
                }
            elif action == "EXIT" and decision == "PLACED" and symbol:
                entry_info = open_positions.get(symbol, {})
                entry_time = entry_info.get("entry_time")
                
                # Fallback to inferring entry time from 'reason' text if missing
                if not entry_time:
                    entry_time = _infer_entry_time(row.get("timestamp"), row.get("reason", ""))
                
                # Parse numeric fields safely
                def _float(val: str) -> float:
                    try:
                        return float(val) if val else 0.0
                    except ValueError:
                        return 0.0
                        
                raw_reason = row.get("reason", "unknown")
                reason_lower = raw_reason.lower()
                if "max hold time" in reason_lower:
                    normalized_reason = f"timeout - {raw_reason}"
                elif "stop-loss" in reason_lower:
                    normalized_reason = f"stop_loss - {raw_reason}"
                elif "take-profit" in reason_lower:
                    normalized_reason = f"take_profit - {raw_reason}"
                else:
                    normalized_reason = raw_reason

                trade = {
                    "entry_time": entry_time,
                    "exit_time": row.get("timestamp"),
                    "exit_reason": normalized_reason,
                    "gross_pnl": _float(row.get("gross_pnl")),
                    "net_pnl": _float(row.get("pnl_usd")),
                    "fees": _float(row.get("fees_paid")),
                    "symbol": symbol,
                    "qty": _float(row.get("qty")),
                    "entry_price": _float(row.get("fill_price")),
                    "exit_price": _float(row.get("exit_price")),
                }
                trades.append(trade)
                # clear position
                if symbol in open_positions:
                    del open_positions[symbol]
                    
    return trades

def main() -> None:
    print("=== P2-037 Journal Provenance ===")
    
    # 1. Discover CSV files (exclude tests/venv)
    candidate_files = []
    scanned_paths = [str(REPO_ROOT)]
    exclude_dirs = {".venv", "tests"}
    for p in REPO_ROOT.rglob("*journal*.csv"):
        if p.is_file() and not any(part in exclude_dirs for part in p.parts):
            candidate_files.append(p)
            
    print(f"Candidate CSV files found: {len(candidate_files)}")
    for cf in candidate_files:
        print(f" - {cf}")
        
    total_exported = 0
    JOURNALS_DIR.mkdir(parents=True, exist_ok=True)
    DIAG_DIR = REPORTS_ROOT / "diagnostics"
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Clean previous exports to avoid stale data during verification
    for old_export in JOURNALS_DIR.glob("export_*.json"):
        try:
            old_export.unlink()
        except Exception:
            pass
            
    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "scanned_paths": scanned_paths,
        "candidate_source_files": [str(p) for p in candidate_files],
        "parsed_source_files": [],
        "ignored_files_with_reasons": {},
        "matched_entries": 0,
        "matched_exits": 0,
        "exported_trade_count": 0,
        "export_directory": str(JOURNALS_DIR),
        "normalized_schema_fields": [
            "entry_time", "exit_time", "exit_reason", "gross_pnl", 
            "net_pnl", "fees", "symbol", "qty", "entry_price", "exit_price"
        ],
        "p2_036_report_path": None,
        "timeout_count": 0,
        "take_profit_count": 0,
        "stop_loss_count": 0,
        "unknown_count": 0,
        "no_historical_trade_data_found": True
    }

    if not candidate_files:
        print("\nNo historical CSV journals found.")
        print("next_action: Run the bot in live/dry_run mode to generate journal files.")
    else:
        # 2. Parse and Export
        for cf in candidate_files:
            try:
                trades = parse_journal_csv(cf)
                report["parsed_source_files"].append(str(cf))
                
                if not trades:
                    report["ignored_files_with_reasons"][str(cf)] = "No closed trades found"
                    continue
                    
                out_name = f"export_{cf.stem}.json"
                out_path = JOURNALS_DIR / out_name
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(trades, f, indent=2, sort_keys=True)
                    
                print(f"\nExtracted {len(trades)} closed trades from {cf.name}")
                print(f"Exported normalized JSON to: {out_path}")
                total_exported += len(trades)
                report["matched_entries"] += len(trades)
                report["matched_exits"] += len(trades)
                
                for trade in trades:
                    r = trade.get("exit_reason", "")
                    if r.startswith("timeout"):
                        report["timeout_count"] += 1
                    elif r.startswith("take_profit"):
                        report["take_profit_count"] += 1
                    elif r.startswith("stop_loss"):
                        report["stop_loss_count"] += 1
                    else:
                        report["unknown_count"] += 1

            except Exception as e:
                report["ignored_files_with_reasons"][str(cf)] = f"Parse error: {e}"
            
        print(f"\nTotal historical trades exported: {total_exported}")
        report["exported_trade_count"] = total_exported
        if total_exported > 0:
            report["no_historical_trade_data_found"] = False
        
        if total_exported == 0:
            print("\nNo valid closed trades found in the candidate files.")
            print("next_action: Confirm that the bot has completed at least one trade lifecycle.")

    # Write provenance report
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    prov_report_path = DIAG_DIR / f"p2_037_journal_provenance_{timestamp}.json"
    with open(prov_report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    print(f"\nProvenance report written to {prov_report_path}")

if __name__ == "__main__":
    main()
