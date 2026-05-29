#!/usr/bin/env python3
"""
controlled_exploration_status.py — Safety report for Coinbase Controlled Exploration.

Checks exploration status, symbol distribution, and risk cap integrity.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import load_config, safe_float

# ── Baseline Risk Caps (P2-001 Verification) ──────────────────────────
BASELINE_CAPS = {
    "daily_stop_loss_usd": 3.00,
    "max_total_exploration_exposure_usd": 6.00,
    "max_single_trade_notional_usd": 1.00,
    "max_round_trips_per_day": 12,
    "max_consecutive_losses": 3,
}

def report_status():
    cfg = load_config()
    
    # 1. Exploration Config
    crypto_cfg = cfg.get("crypto", {})
    exp_cfg = crypto_cfg.get("controlled_exploration", {})
    
    enabled = exp_cfg.get("enabled", False)
    approved_symbols = exp_cfg.get("approved_symbols", [])
    notional = exp_cfg.get("max_single_trade_notional_usd", 1.00)
    legacy_disabled = exp_cfg.get("disable_legacy_btc_probe_when_enabled", False)
    
    print("=== Controlled Exploration Status ===")
    print(f"Enabled:          {enabled}")
    print(f"Approved Symbols: {', '.join(approved_symbols)}")
    print(f"Max Notional:     ${notional:.2f}")
    print(f"Legacy BTC Probe disabled: {legacy_disabled if enabled else 'n/a'}")
    print("")

    # 2. Risk Cap Integrity
    print("=== Risk Cap Integrity (vs Baseline) ===")
    caps_consistent = True
    
    for key, baseline in BASELINE_CAPS.items():
        current = safe_float(exp_cfg.get(key))
        status = "OK" if current <= baseline else "INCREASED (WARNING)"
        if current > baseline:
            caps_consistent = False
        print(f"{key:35} | Current: {current:6.2f} | Baseline: {baseline:6.2f} | {status}")
    
    if caps_consistent:
        print("RESULT: Risk caps are UNCHANGED or REDUCED. Safety baseline maintained.")
    else:
        print("RESULT: Risk caps have been INCREASED. Safety baseline VIOLATED.")
    print("")

    # 3. Activity (from Journal)
    journal_file = cfg.get("logging", {}).get("journal_file", "journal.csv")
    journal_path = ROOT / journal_file
    
    daily_trades = 0
    trades_by_symbol = Counter()
    last_symbol = "n/a"
    reject_reasons = []
    open_positions = 0
    
    if journal_path.exists():
        try:
            with open(journal_path, "r", newline="") as f:
                rows = list(csv.DictReader(f))
                now = datetime.now(timezone.utc)
                
                for row in rows:
                    raw_ts = row.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                        if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
                    except: continue
                    
                    # Last 24h
                    if (now - ts).total_seconds() < 24 * 3600:
                        strategy = row.get("strategy", "")
                        decision = row.get("decision", "")
                        symbol = row.get("symbol", "")
                        
                        if strategy == "coinbase_exploration":
                            if decision == "FILLED":
                                daily_trades += 1
                                trades_by_symbol[symbol] += 1
                                last_symbol = symbol
                            elif decision == "SKIPPED":
                                reject_reasons.append(row.get("reason", "unknown"))

                if rows:
                    last_row = rows[-1]
                    open_positions = int(safe_float(last_row.get("open_positions", 0)))
        except Exception as e:
            print(f"Error reading journal: {e}")

    print("=== Recent Activity (Last 24h) ===")
    print(f"Daily Trades (Exploration): {daily_trades}")
    print(f"Trades by Symbol:           {dict(trades_by_symbol)}")
    print(f"Last Selected Symbol:       {last_symbol}")
    print(f"Open Positions (Estimated): {open_positions}")
    print("")

    print("=== Recent Reject Reasons ===")
    if reject_reasons:
        for r in Counter(reject_reasons).most_common(5):
            print(f"  - {r[0]}: {r[1]}")
    else:
        print("  None found.")
    print("")

    # 4. Recommendation
    print("=== Recommendation ===")
    if not enabled:
        print("Exploration is DISABLED. Enable it in config_coinbase_crypto.yaml to start.")
    elif daily_trades >= exp_cfg.get("max_round_trips_per_day", 12):
        print("Daily limit reached. Bot will sit out until reset.")
    else:
        print("Exploration ACTIVE. Monitoring for diverse opportunities.")
    print("No live orders placed by this script.")
    print("")

if __name__ == "__main__":
    report_status()
