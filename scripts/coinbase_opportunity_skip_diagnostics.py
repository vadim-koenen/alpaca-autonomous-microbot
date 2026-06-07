#!/usr/bin/env python3
"""
P2-030A Coinbase Opportunity / Skip Diagnostics (Read-Only).

Analyzes heartbeats, journals, and local state to explain why the bot
is or is not entering trades.

This script is strictly READ-ONLY and does not mutate any state.
"""

import argparse
import csv
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0"
REPORT_CLASS = "coinbase_opportunity_skip_diagnostics"

def parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text or text == "None":
        return None
    try:
        # fromisoformat handles Z and offsets in modern python
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None

def read_json(path: Path) -> Tuple[Any, Optional[str]]:
    if not path.exists():
        return {}, "missing"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return {}, str(e)

def read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def get_git_head(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], 
            cwd=repo_root, 
            stderr=subprocess.STDOUT,
            text=True
        ).strip()
    except Exception:
        return "unknown"

def build_report(
    repo_root: Path,
    lookback_hours: int = 24,
    now: Optional[datetime] = None
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    lookback_limit = now - timedelta(hours=lookback_hours)
    
    heartbeat_path = repo_root / "runtime" / "coinbase_heartbeat.json"
    heartbeat, hb_err = read_json(heartbeat_path)
    
    open_positions_path = repo_root / "state" / "coinbase" / "open_positions.json"
    open_positions_data, _ = read_json(open_positions_path)
    local_open_positions = []
    if isinstance(open_positions_data, dict):
        pos_dict = open_positions_data.get("positions", open_positions_data)
        if isinstance(pos_dict, dict):
            local_open_positions = [str(k) for k in pos_dict.keys() if isinstance(pos_dict[k], dict)]

    journal_path = repo_root / "journal_coinbase_crypto.csv"
    journal_rows = []
    if journal_path.exists():
        try:
            with journal_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ts = parse_time(row.get("timestamp"))
                    if ts and ts >= lookback_limit:
                        journal_rows.append(row)
        except Exception:
            pass

    # Summarize journal
    buy_count = 0
    sell_count = 0
    skip_count = 0
    skip_reasons = Counter()
    decisions = []
    
    for row in journal_rows:
        action = str(row.get("action") or "").upper()
        decision = str(row.get("decision") or "").upper()
        reason = str(row.get("reason") or "")
        
        if decision == "SKIP" or "SKIPPED" in decision:
            skip_count += 1
            if reason:
                skip_reasons[reason] += 1
        elif action == "BUY" and decision == "PLACED":
            buy_count += 1
        elif action == "EXIT" and decision == "PLACED":
            sell_count += 1
        
        decisions.append({
            "timestamp": row.get("timestamp"),
            "symbol": row.get("symbol"),
            "action": action,
            "decision": decision,
            "reason": reason
        })

    stop_trading_present = (repo_root / "runtime" / "STOP_TRADING").exists()
    
    # Identify blocking reasons
    blocking_reasons = []
    if stop_trading_present:
        blocking_reasons.append("STOP_TRADING present")
    
    risk_halt = heartbeat.get("risk_halt_active")
    if risk_halt:
        blocking_reasons.append(f"Risk halt active: {heartbeat.get('halt_reason')}")
    
    hb_time = parse_time(heartbeat.get("last_loop_time"))
    hb_stale = False
    if not hb_time or (now - hb_time).total_seconds() > 600:
        hb_stale = True
        if hb_time:
            blocking_reasons.append(f"Stale heartbeat (last seen {hb_time.isoformat()})")
        else:
            blocking_reasons.append("Missing or invalid heartbeat")

    # Analyze skips for more blockers
    top_skips = skip_reasons.most_common(5)
    for reason, count in top_skips:
        reason_lower = reason.lower()
        if "max_open_positions" in reason_lower or "position cap" in reason_lower:
            blocking_reasons.append(f"Position cap reached ({count} skips)")
        elif "daily_trade_count" in reason_lower or "daily cap" in reason_lower:
            blocking_reasons.append(f"Daily trade cap reached ({count} skips)")
        elif "buying_power" in reason_lower or "insufficient funds" in reason_lower:
            blocking_reasons.append(f"Low buying power ({count} skips)")

    # Recommended next action
    if blocking_reasons:
        recommended = f"Resolve blockers: {', '.join(blocking_reasons)}"
    elif not journal_rows:
        recommended = "No journal activity found in lookback window. Check if bot is running and market data is flowing."
    elif skip_count > 0:
        recommended = f"Investigate top skip reasons: {top_skips[0][0] if top_skips else 'N/A'}"
    else:
        recommended = "No clear blockers found. Strategy might not be finding signals or spread guard is too tight."

    config = read_yaml(repo_root / "config_coinbase_crypto.yaml")
    risk_config = config.get("global_risk", {})
    crypto_config = config.get("crypto", {})

    report = {
        "report_class": REPORT_CLASS,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "git_head": get_git_head(repo_root),
        "mode_detected": heartbeat.get("mode", "unknown"),
        "stop_trading_present": stop_trading_present,
        "heartbeat": {
            "status": heartbeat.get("status"),
            "fresh": not hb_stale,
            "last_loop_time": heartbeat.get("last_loop_time"),
            "risk_halt_active": risk_halt,
            "halt_reason": heartbeat.get("halt_reason")
        },
        "runtime_health": "OK" if not (stop_trading_present or hb_stale or risk_halt) else "BLOCKED",
        "risk_config_detected": {
            "max_open_positions": risk_config.get("max_open_positions"),
            "max_trades_per_day": risk_config.get("max_trades_per_day"),
            "max_trade_notional_usd": crypto_config.get("max_trade_notional_usd")
        },
        "account_snapshot_from_heartbeat": {
            "equity": heartbeat.get("equity"),
            "buying_power": heartbeat.get("buying_power"),
            "consecutive_losses": heartbeat.get("consecutive_losses")
        },
        "local_open_positions": local_open_positions,
        "recent_journal_summary": {
            "buy_count": buy_count,
            "sell_count": sell_count,
            "skip_count": skip_count
        },
        "recent_trade_decisions": decisions[-20:],
        "recent_skips_by_reason": dict(skip_reasons),
        "symbols_evaluated": sorted(list(set(d["symbol"] for d in decisions if d["symbol"]))),
        "candidate_opportunities": [],
        "blocking_reasons": blocking_reasons,
        "profitability_relevance": {
            "trades_today": heartbeat.get("trades_today"),
            "last_trade_at": heartbeat.get("last_trade_at"),
            "last_exit_at": heartbeat.get("last_exit_at"),
            "daily_pnl": heartbeat.get("daily_pnl"),
            "decision_count_window": len(journal_rows),
            "skipped_count_window": skip_count,
            "top_skip_reasons": [f"{r}: {c}" for r, c in top_skips]
        },
        "recommended_next_action": recommended,
        "next_best_investigation": recommended,
        "order_mutation_performed": False,
        "state_mutation_performed": False,
        "broker_mutation_performed": False
    }
    return report

def render_summary(report: Dict[str, Any]) -> str:
    lines = [
        "=== Coinbase Opportunity / Skip Diagnostics ===",
        f"Generated at: {report['generated_at_utc']}",
        f"Runtime Health: {report['runtime_health']}",
        f"STOP_TRADING: {report['stop_trading_present']}",
        f"Heartbeat Fresh: {report['heartbeat']['fresh']}",
        "",
        "--- Recent Activity (Lookback) ---",
        f"Buy Placed: {report['recent_journal_summary']['buy_count']}",
        f"Exit Placed: {report['recent_journal_summary']['sell_count']}",
        f"Skips: {report['recent_journal_summary']['skip_count']}",
        "",
        "--- Top Skip Reasons ---",
    ]
    if not report["profitability_relevance"]["top_skip_reasons"]:
        lines.append("  (None)")
    for reason in report["profitability_relevance"]["top_skip_reasons"]:
        lines.append(f"  - {reason}")
    
    if report["blocking_reasons"]:
        lines.append("")
        lines.append("--- Blocking Reasons ---")
        for reason in report["blocking_reasons"]:
            lines.append(f"  !! {reason}")

    lines.append("")
    lines.append(f"Recommended Action: {report['recommended_next_action']}")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Coinbase Opportunity / Skip Diagnostics")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-broker", action="store_true", default=True)
    
    args = parser.parse_args()
    
    report = build_report(args.repo_root, args.lookback_hours)
    
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = args.output_dir / f"coinbase_opportunity_skip_diagnostics_{ts}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
        if not args.json:
            print(f"Report written to: {out_path}")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_summary(report))

if __name__ == "__main__":
    main()
