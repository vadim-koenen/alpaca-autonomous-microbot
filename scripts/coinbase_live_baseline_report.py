#!/usr/bin/env python3
# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Coinbase Live-Only Performance Re-Baseline — P2-001H

Analyzes Coinbase exploration trades with strict filters:
- mode == "live"
- strategy == "coinbase_exploration"
- symbol in ["BTC/USD", "ETH/USD", "SOL/USD"]
Excludes ALGO/USD, probe, recovered, and dry_run data.
"""

import csv
import sys
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

APPROVED_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]

def classify_exit_reason(reason_text):
    if not reason_text or not isinstance(reason_text, str):
        return 'other'
    
    reason_lower = reason_text.lower()
    
    if 'stop loss' in reason_lower or 'stop-loss' in reason_lower:
        return 'stop_loss'
    if 'take profit' in reason_lower or 'take-profit' in reason_lower:
        return 'take_profit'
    if 'max hold' in reason_lower:
        return 'max_hold'
    
    return 'other'

def parse_hold_time(reason_text):
    if not reason_text:
        return None
    match = re.search(r'\((\d+\.?\d*)min held\)', reason_text)
    if match:
        return float(match.group(1))
    return None

def run_baseline_report(journal_path):
    if not Path(journal_path).exists():
        print(f"Error: Journal not found at {journal_path}")
        return None

    exits = []
    try:
        with open(journal_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # MANDATORY FILTERS
                if (row.get('mode') == 'live' and 
                    row.get('strategy') == 'coinbase_exploration' and 
                    row.get('symbol') in APPROVED_SYMBOLS and
                    row.get('action') == 'EXIT' and
                    row.get('decision') in ['PLACED', 'FILLED']):
                    
                    try:
                        exits.append({
                            'timestamp': row.get('timestamp', ''),
                            'symbol': row.get('symbol', ''),
                            'reason': row.get('reason', ''),
                            'fill_price': float(row.get('fill_price') or 0),
                            'exit_price': float(row.get('exit_price') or 0),
                            'pnl_usd': float(row.get('pnl_usd') or 0),
                            'pnl_pct': float(row.get('pnl_pct') or 0),
                            'fees_paid': float(row.get('fees_paid') or 0),
                            'gross_pnl': float(row.get('gross_pnl') or 0),
                        })
                    except ValueError:
                        continue
    except Exception as e:
        print(f"Error reading journal: {e}")
        return None

    if not exits:
        return {'total_exits': 0}

    stats = {
        'total_exits': len(exits),
        'total_gross_pnl': sum(e['gross_pnl'] for e in exits),
        'total_fees': sum(e['fees_paid'] for e in exits),
        'total_net_pnl': sum(e['pnl_usd'] for e in exits),
        'net_wins': sum(1 for e in exits if e['pnl_usd'] > 0),
        'gross_wins': sum(1 for e in exits if e['gross_pnl'] > 0),
        'by_symbol': defaultdict(list),
        'by_exit_type': defaultdict(list),
        'mfe_records': [],
        'mae_records': [],
        'hold_times': []
    }

    for e in exits:
        stats['by_symbol'][e['symbol']].append(e)
        exit_type = classify_exit_reason(e['reason'])
        stats['by_exit_type'][exit_type].append(e)
        
        hold_time = parse_hold_time(e['reason'])
        if hold_time is not None:
            stats['hold_times'].append(hold_time)
            
        if e['fill_price'] > 0 and e['exit_price'] > 0:
            move_pct = (e['exit_price'] - e['fill_price']) / e['fill_price'] * 100
            stats['mfe_records'].append(max(0, move_pct))
            stats['mae_records'].append(max(0, -move_pct))

    return stats

def print_report(stats):
    if not stats or stats['total_exits'] == 0:
        print("\n" + "="*60)
        print("COINBASE LIVE-ONLY BASELINE REPORT — P2-001H")
        print("="*60)
        print("No qualifying live exploration exits found in journal.")
        print("Required filters: mode=live, strategy=coinbase_exploration, symbol in [BTC/USD, ETH/USD, SOL/USD]")
        return

    print("\n" + "="*60)
    print("COINBASE LIVE-ONLY BASELINE REPORT — P2-001H")
    print("="*60)
    print(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total Live-Only Exits: {stats['total_exits']}")
    
    if stats['total_exits'] < 10:
        print("\n⚠️  WARNING: Data is too sparse for high confidence.")

    print("\n1. LIVE-ONLY PERFORMANCE SUMMARY")
    print("-" * 40)
    print(f"  Gross Win Rate:   {stats['gross_wins']}/{stats['total_exits']} ({stats['gross_wins']/stats['total_exits']*100:5.1f}%)")
    print(f"  Net Win Rate:     {stats['net_wins']}/{stats['total_exits']} ({stats['net_wins']/stats['total_exits']*100:5.1f}%)")
    print(f"  Total Gross P/L:  ${stats['total_gross_pnl']:8.4f}")
    print(f"  Total Fees Paid:  ${stats['total_fees']:8.4f}")
    print(f"  Total Net P/L:    ${stats['total_net_pnl']:8.4f}")
    print(f"  Avg Net P/L:      ${stats['total_net_pnl']/stats['total_exits']:8.4f} per trade")

    print("\n2. LIVE-ONLY EXIT QUALITY SUMMARY")
    print("-" * 40)
    for etype in ['max_hold', 'stop_loss', 'take_profit', 'other']:
        records = stats['by_exit_type'].get(etype, [])
        count = len(records)
        avg_pnl = sum(r['pnl_usd'] for r in records) / count if count > 0 else 0
        print(f"  {etype.upper():12}: {count:3} exits | Avg Net: ${avg_pnl:8.4f}")

    if stats['by_exit_type'].get('max_hold') and len(stats['by_exit_type']['max_hold']) == stats['total_exits']:
        print("\n  ⚠️  WARNING: 100% of exits are max_hold. Thresholds never triggered.")

    if stats['mfe_records']:
        avg_mfe = sum(stats['mfe_records']) / len(stats['mfe_records'])
        max_mfe = max(stats['mfe_records'])
        avg_mae = sum(stats['mae_records']) / len(stats['mae_records'])
        max_mae = max(stats['mae_records'])
        print(f"\n  Avg MFE: {avg_mfe:5.2f}% | Max MFE: {max_mfe:5.2f}%")
        print(f"  Avg MAE: {avg_mae:5.2f}% | Max MAE: {max_mae:5.2f}%")
        print("  (MFE/MAE computed from realized fill vs exit price only)")

    if stats['hold_times']:
        avg_hold = sum(stats['hold_times']) / len(stats['hold_times'])
        print(f"  Avg Hold Time: {avg_hold:5.1f} minutes")

    print("\n3. MAKER/TAKER BREAK-EVEN COMPARISON")
    print("-" * 40)
    avg_mfe = (sum(stats['mfe_records']) / len(stats['mfe_records'])) if stats['mfe_records'] else 0
    max_mfe = max(stats['mfe_records']) if stats['mfe_records'] else 0
    
    print(f"  Maker Break-even: 1.2% round-trip")
    print(f"  Taker Break-even: 2.4% round-trip")
    print(f"  Max Realized MFE: {max_mfe:5.2f}%")
    
    if max_mfe > 1.2:
        print("  ADVISORY: Max MFE exceeds maker break-even. Tuning may be plausible if using maker fees.")
    else:
        print("  ADVISORY: Max MFE remains below break-even. Expectancy is currently negative.")

    print("\n4. PER-SYMBOL WIN RATE (LIVE-ONLY)")
    print("-" * 40)
    for symbol in APPROVED_SYMBOLS:
        records = stats['by_symbol'].get(symbol, [])
        count = len(records)
        if count > 0:
            wins = sum(1 for r in records if r['pnl_usd'] > 0)
            net_pnl = sum(r['pnl_usd'] for r in records)
            avg_pct = sum(r['pnl_pct'] for r in records) / count
            print(f"  {symbol:10}: {count:3} trades | Win Rate: {wins/count*100:5.1f}% | Avg Net %: {avg_pct:6.2f}%")
        else:
            print(f"  {symbol:10}: No Qualifying Data")

    print("\n5. ADVISORY VERDICT")
    print("-" * 40)
    net_pnl = stats['total_net_pnl']
    if net_pnl < 0:
        print("  VERDICT: Live-only expectancy is currently NEGATIVE.")
        print("  More clean live-only sample collection is HIGHLY RECOMMENDED before Class 2 tuning.")
    else:
        print("  VERDICT: Live-only expectancy is positive, but check sample size confidence.")
    
    print("\n  LIMITATIONS: Journal lacks intratrade price path. True MFE/MAE may be higher.")
    print("  ADVISORY ONLY: Do not change config based solely on this report.")
    print("="*60 + "\n")

if __name__ == "__main__":
    journal = "journal_coinbase_crypto.csv"
    results = run_baseline_report(journal)
    print_report(results)
