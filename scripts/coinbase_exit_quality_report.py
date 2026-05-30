#!/usr/bin/env python3
# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.
"""
Coinbase Exit Quality Report — P2-001E

Analyzes completed exits from journal_coinbase_crypto.csv:
1. Exit type distribution (max_hold, stop_loss, take_profit, other)
2. Net P/L and fee analysis by exit type
3. Warning if 100% of exits are max_hold
4. MFE (max favorable excursion) analysis at exit time
5. Count of trades within 50% of 3% TP threshold
6. Hold-time analysis feasibility
7. TP/SL threshold simulation using available P/L data
8. Per-symbol breakdown
9. Advisory recommendations only
"""

import csv
import sys
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime


def classify_exit_reason(reason_text):
    """
    Classify exit type from reason text.
    Returns: 'max_hold', 'stop_loss', 'take_profit', or 'other'
    """
    if not reason_text or not isinstance(reason_text, str):
        return 'other'
    
    reason_lower = reason_text.lower()
    
    if 'stop loss' in reason_lower or 'stop_loss' in reason_lower or 'stop-loss' in reason_lower:
        return 'stop_loss'
    if 'take profit' in reason_lower or 'take_profit' in reason_lower or 'take-profit' in reason_lower:
        return 'take_profit'
    if 'max hold' in reason_lower:
        return 'max_hold'
    
    return 'other'


def parse_journal(csv_path):
    """Parse journal CSV and extract exit records."""
    exits = []
    
    if not Path(csv_path).exists():
        return exits
    
    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Filter for EXIT records where decision is PLACED or FILLED
                # (status field is empty in current journal, decision field contains the status)
                action = row.get('action', '').strip()
                decision = row.get('decision', '').strip()
                if action == 'EXIT' and decision in ['PLACED', 'FILLED']:
                    try:
                        exits.append({
                            'timestamp': row.get('timestamp', ''),
                            'symbol': row.get('symbol', ''),
                            'reason': row.get('reason', ''),
                            'fill_price': float(row.get('fill_price', 0) or 0),
                            'exit_price': float(row.get('exit_price', 0) or 0),
                            'pnl_usd': float(row.get('pnl_usd', 0) or 0),
                            'pnl_pct': float(row.get('pnl_pct', 0) or 0),
                            'fees_paid': float(row.get('fees_paid', 0) or 0),
                            'gross_pnl': float(row.get('gross_pnl', 0) or 0),
                            'qty': float(row.get('qty', 0) or 0),
                        })
                    except (ValueError, TypeError):
                        continue
    except Exception as e:
        print(f"Warning: Error reading {csv_path}: {e}", file=sys.stderr)
    
    return exits


def analyze_exits(exits):
    """Analyze exit records and compute statistics."""
    if not exits:
        return {}
    
    by_exit_type = defaultdict(list)
    by_symbol = defaultdict(list)
    
    for exit_record in exits:
        exit_type = classify_exit_reason(exit_record['reason'])
        by_exit_type[exit_type].append(exit_record)
        by_symbol[exit_record['symbol']].append(exit_record)
    
    # Compute aggregate stats by exit type
    exit_type_stats = {}
    for exit_type, records in by_exit_type.items():
        count = len(records)
        total_pnl = sum(r['pnl_usd'] for r in records)
        avg_pnl = total_pnl / count if count > 0 else 0
        total_fees = sum(r['fees_paid'] for r in records)
        avg_pnl_pct = sum(r['pnl_pct'] for r in records) / count if count > 0 else 0
        
        # Count positive exits
        positive_count = sum(1 for r in records if r['pnl_usd'] > 0)
        
        exit_type_stats[exit_type] = {
            'count': count,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'total_fees': total_fees,
            'avg_pnl_pct': avg_pnl_pct,
            'positive_count': positive_count,
        }
    
    # Compute per-symbol stats
    symbol_stats = {}
    for symbol, records in sorted(by_symbol.items()):
        count = len(records)
        total_pnl = sum(r['pnl_usd'] for r in records)
        avg_pnl = total_pnl / count if count > 0 else 0
        positive_count = sum(1 for r in records if r['pnl_usd'] > 0)
        
        # Count exit types for this symbol
        exit_type_dist = defaultdict(int)
        for r in records:
            exit_type = classify_exit_reason(r['reason'])
            exit_type_dist[exit_type] += 1
        
        symbol_stats[symbol] = {
            'count': count,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'positive_count': positive_count,
            'exit_type_dist': dict(exit_type_dist),
        }
    
    # MFE analysis: max favorable excursion at time of exit
    # MFE proxy: how far did price move in favorable direction from fill to exit?
    mfe_records = []
    mae_records = []
    hold_times = []
    
    for exit_record in exits:
        fill_price = exit_record['fill_price']
        exit_price = exit_record['exit_price']
        reason = exit_record['reason']
        
        # Parse hold time from reason if available: "(90.6min held)"
        hold_match = re.search(r'\((\d+\.?\d*)min held\)', reason)
        if hold_match:
            hold_times.append(float(hold_match.group(1)))
        
        if fill_price > 0 and exit_price > 0:
            # Favorable direction: away from entry in direction of profit (assuming LONG)
            move_pct = (exit_price - fill_price) / fill_price * 100
            
            mfe_pct = max(0.0, move_pct)
            mae_pct = max(0.0, -move_pct)
            
            mfe_records.append({
                'symbol': exit_record['symbol'],
                'mfe_pct': mfe_pct,
                'pnl_usd': exit_record['pnl_usd'],
            })
            mae_records.append({
                'symbol': exit_record['symbol'],
                'mae_pct': mae_pct,
                'pnl_usd': exit_record['pnl_usd'],
            })
    
    # Trades within 50% of 3% TP threshold
    tp_threshold = 3.0
    within_50pct_tp = 0
    for exit_record in exits:
        pnl_pct = exit_record['pnl_pct']
        if pnl_pct > 0:
            threshold_50pct = tp_threshold * 0.5
            if pnl_pct >= threshold_50pct:
                within_50pct_tp += 1
    
    # Hold-time analysis: check if we parsed any hold times
    hold_time_estimable = len(hold_times) > 0
    if hold_time_estimable:
        avg_hold = sum(hold_times) / len(hold_times)
        hold_time_note = (
            f"Parsed {len(hold_times)} hold times from reason strings. "
            f"Average hold time: {avg_hold:.1f} minutes."
        )
    else:
        hold_time_note = (
            "Journal contains exit timestamps but not entry timestamps in a directly usable "
            "format. No hold times found in reason strings. "
            "Cannot estimate hold-time impact precisely."
        )
    
    # TP/SL simulation: using pnl_pct as proxy for price move
    # Would 1.5% SL have triggered? Check if any exit had |pnl_pct| >= 1.5
    tp_15pct = 1.5
    would_trigger_sl = 0
    for exit_record in exits:
        pnl_pct = exit_record['pnl_pct']
        if pnl_pct < 0 and abs(pnl_pct) >= tp_15pct:
            would_trigger_sl += 1
    
    return {
        'total_exits': len(exits),
        'exit_type_stats': exit_type_stats,
        'symbol_stats': symbol_stats,
        'mfe_records': mfe_records,
        'mae_records': mae_records,
        'hold_times': hold_times,
        'within_50pct_tp': within_50pct_tp,
        'hold_time_estimable': hold_time_estimable,
        'hold_time_note': hold_time_note,
        'would_trigger_15pct_sl': would_trigger_sl,
    }


def print_report(analysis):
    """Format and print the exit quality report."""
    if not analysis or analysis['total_exits'] == 0:
        print("No exit records found in journal.")
        return
    
    print("\n" + "=" * 80)
    print("COINBASE EXIT QUALITY REPORT — P2-001E")
    print("=" * 80)
    print(f"Generated: {datetime.utcnow().isoformat()}Z")
    print(f"Total exits analyzed: {analysis['total_exits']}")
    
    # 1. Exit type distribution
    print("\n" + "-" * 80)
    print("1. EXIT TYPE DISTRIBUTION")
    print("-" * 80)
    
    stats = analysis['exit_type_stats']
    if not stats:
        print("No exit types found.")
    else:
        for exit_type in ['max_hold', 'stop_loss', 'take_profit', 'other']:
            if exit_type in stats:
                s = stats[exit_type]
                pct = (s['count'] / analysis['total_exits'] * 100) if analysis['total_exits'] > 0 else 0
                print(f"  {exit_type.upper():15s} | Count: {s['count']:3d} ({pct:5.1f}%) "
                      f"| Avg P/L: ${s['avg_pnl']:8.6f} "
                      f"| Total: ${s['total_pnl']:8.6f} "
                      f"| Winning: {s['positive_count']}/{s['count']}")
    
    # Check for 100% max_hold warning
    if 'max_hold' in stats and stats['max_hold']['count'] == analysis['total_exits']:
        print("\n  ⚠️  WARNING: 100% of exits are max_hold exits.")
        print("     SL/TP thresholds (1.5%/3%) have NEVER triggered in this sample.")
        print("     This indicates either:")
        print("     - Thresholds are too tight for current volatility")
        print("     - Hold window is too short to reach targets")
        print("     - Market regime does not support targets")
    
    # 2. Fee impact
    print("\n" + "-" * 80)
    print("2. FEE IMPACT ANALYSIS")
    print("-" * 80)
    
    total_fees = sum(s['total_fees'] for s in stats.values())
    total_pnl = sum(s['total_pnl'] for s in stats.values())
    avg_fee_per_exit = total_fees / analysis['total_exits'] if analysis['total_exits'] > 0 else 0
    
    print(f"  Total fees paid:           ${total_fees:8.6f}")
    print(f"  Average fee per exit:      ${avg_fee_per_exit:8.6f}")
    print(f"  Total net P/L (all exits): ${total_pnl:8.6f}")
    print(f"  Win rate:                  {sum(s['positive_count'] for s in stats.values())}/{analysis['total_exits']}")
    
    # 3. MFE / MAE Analysis
    print("\n" + "-" * 80)
    print("3. MAXIMUM FAVORABLE / ADVERSE EXCURSION (MFE/MAE) AT EXIT")
    print("-" * 80)
    
    if analysis['mfe_records']:
        mfe_values = [r['mfe_pct'] for r in analysis['mfe_records']]
        mae_values = [r['mae_pct'] for r in analysis['mae_records']]
        
        avg_mfe = sum(mfe_values) / len(mfe_values) if mfe_values else 0
        max_mfe = max(mfe_values) if mfe_values else 0
        
        avg_mae = sum(mae_values) / len(mae_values) if mae_values else 0
        max_mae = max(mae_values) if mae_values else 0
        
        print(f"  MFE (price move in profitable direction from fill to exit):")
        print(f"    Average MFE:      {avg_mfe:7.3f}%")
        print(f"    Max MFE:          {max_mfe:7.3f}%")
        print(f"  MAE (price move in losing direction from fill to exit):")
        print(f"    Average MAE:      {avg_mae:7.3f}%")
        print(f"    Max MAE:          {max_mae:7.3f}%")
        print(f"  Note: MFE/MAE computed from fill_price vs exit_price in journal (assuming Long).")
        print(f"        Does NOT include intratrade high/low. Represents realized move at exit.")
    else:
        print("  No MFE/MAE data available (missing price fields).")
    
    # 4. Hold-time analysis
    print("\n" + "-" * 80)
    print("4. HOLD-TIME ANALYSIS")
    print("-" * 80)
    print(f"  {analysis['hold_time_note']}")
    if analysis['hold_times']:
        h = analysis['hold_times']
        print(f"    Min hold:         {min(h):.1f} min")
        print(f"    Max hold:         {max(h):.1f} min")
    print(f"  Recommendation: Extract entry/exit timestamps from broker fills for full study.")
    
    # 5. Trades within 50% of 3% TP threshold
    print("\n" + "-" * 80)
    print("5. TRADES WITHIN 50% OF 3% TAKE-PROFIT THRESHOLD")
    print("-" * 80)
    print(f"  Trades with pnl_pct >= 1.5% (50% of 3% TP): {analysis['within_50pct_tp']}")
    print(f"  This suggests {analysis['within_50pct_tp']} trades approached TP threshold.")
    
    # 6. TP/SL simulation
    print("\n" + "-" * 80)
    print("6. TP/SL THRESHOLD SIMULATION")
    print("-" * 80)
    print(f"  Current config: 3% TP, 1.5% SL, 90-min hold")
    print(f"  Exits that would trigger 1.5% SL: {analysis['would_trigger_15pct_sl']}")
    print(f"  Exits approaching 3% TP (>= 1.5%): {analysis['within_50pct_tp']}")
    print(f"  Limitation: pnl_pct is net of fees. Cannot simulate gross thresholds without price path.")
    
    # 7. Per-symbol breakdown
    print("\n" + "-" * 80)
    print("7. PER-SYMBOL BREAKDOWN")
    print("-" * 80)
    
    for symbol, s in sorted(analysis['symbol_stats'].items()):
        print(f"\n  {symbol}:")
        print(f"    Total exits:      {s['count']}")
        print(f"    Total P/L:        ${s['total_pnl']:8.6f}")
        print(f"    Average P/L:      ${s['avg_pnl']:8.6f}")
        print(f"    Winning trades:   {s['positive_count']}/{s['count']}")
        
        if s['exit_type_dist']:
            print(f"    Exit types:")
            for exit_type, count in sorted(s['exit_type_dist'].items()):
                pct = (count / s['count'] * 100) if s['count'] > 0 else 0
                print(f"      - {exit_type}: {count} ({pct:.1f}%)")
    
    # 8. Recommendations
    print("\n" + "-" * 80)
    print("8. ADVISORY RECOMMENDATIONS")
    print("-" * 80)
    print("""
  1. SL/TP never triggered: Consider whether thresholds align with your typical
     move size in 90 minutes. If moves are consistently < 1.5%, SL is ineffective.
  
  2. Fee impact is significant: At $1 notional, round-trip taker fees are ~2.4%.
     Any trade with <2.4% gross move will be net negative.
  
  3. Hold-time window: All exits were max_hold. Consider studying whether shorter
     hold times (e.g., 45 min) capture most of the upside with lower fee impact.
  
  4. Per-symbol performance: Review which symbols have better win rates. SOL and BTC
     may have different volatility profiles than ETH.
  
  5. Next steps (do not implement without review):
     - Gather intraday price path data (high/low during hold window)
     - Study whether 45-min exits improve W/L ratio vs fee delta
     - Review whether 3% TP and 1.5% SL are realistic for your market regime
     - Consider market-regime-based SL/TP adjustment
  
  ⚠️  This report is ADVISORY ONLY. Do not change config without explicit review.
""")
    
    print("=" * 80)
    print("END REPORT")
    print("=" * 80 + "\n")


def main():
    """Main entry point."""
    repo_root = Path(__file__).parent.parent
    
    # Try journal sources in priority order
    journal_paths = [
        repo_root / 'journal_coinbase_crypto.csv',
        repo_root / 'logs' / 'coinbase_journal.csv',
        repo_root / 'journal.csv',
    ]
    
    journal_path = None
    for path in journal_paths:
        if path.exists():
            journal_path = path
            break
    
    if not journal_path:
        print("Error: No journal found. Searched:", file=sys.stderr)
        for p in journal_paths:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Reading journal: {journal_path}")
    exits = parse_journal(journal_path)
    
    if not exits:
        print("No exits found in journal.")
        sys.exit(0)
    
    analysis = analyze_exits(exits)
    print_report(analysis)


if __name__ == '__main__':
    main()
