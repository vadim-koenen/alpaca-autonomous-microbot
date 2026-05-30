# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Coinbase Maker Order Audit — P2-001F

Analyzes whether entries for the coinbase_exploration strategy are likely
maker-priced entries (passive) or likely taker-priced entries (aggressive).
"""

import csv
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def classify_fill(fill_price, bid, ask):
    """
    Classify a fill as likely_maker, likely_taker, or unknown.
    A BUY order is likely a maker if it fills at or below the midpoint.
    It is likely a taker if it fills at or near the ask.
    """
    if fill_price <= 0 or bid <= 0 or ask <= 0:
        return 'unknown'
    
    mid = (bid + ask) / 2
    
    # Likely maker: fill price is at or below midpoint
    if fill_price <= mid:
        return 'likely_maker'
    
    # Likely taker: fill price is at or above ask (or very close to it)
    # Using a tiny epsilon or just > mid for simpler classification
    if fill_price >= ask:
        return 'likely_taker'
    
    # Between mid and ask: could be a partial fill or shifting market,
    # but usually more taker-like in execution if above mid.
    return 'likely_taker'

def run_audit(journal_path):
    if not Path(journal_path).exists():
        print(f"Error: Journal not found at {journal_path}")
        return None

    stats = {
        'total_entries': 0,
        'order_types': defaultdict(int),
        'classifications': defaultdict(int),
        'by_symbol': defaultdict(lambda: {
            'total': 0,
            'classifications': defaultdict(int),
            'order_types': defaultdict(int)
        }),
        'limit_order_details': []
    }

    try:
        with open(journal_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Filter criteria: mode=live, strategy=coinbase_exploration, action=BUY, decision=PLACED
                if (row.get('mode') == 'live' and 
                    row.get('strategy') == 'coinbase_exploration' and 
                    row.get('action') == 'BUY' and 
                    row.get('decision') == 'PLACED'):
                    
                    symbol = row.get('symbol', 'UNKNOWN')
                    order_type = row.get('order_type', 'unknown').lower()
                    
                    # For PLACED buy orders, 'price' is the limit price (the intended fill price)
                    try:
                        price = float(row.get('price') or 0)
                        bid = float(row.get('bid') or 0)
                        ask = float(row.get('ask') or 0)
                    except ValueError:
                        price = bid = ask = 0.0

                    classification = classify_fill(price, bid, ask)
                    
                    stats['total_entries'] += 1
                    stats['order_types'][order_type] += 1
                    stats['classifications'][classification] += 1
                    
                    stats['by_symbol'][symbol]['total'] += 1
                    stats['by_symbol'][symbol]['classifications'][classification] += 1
                    stats['by_symbol'][symbol]['order_types'][order_type] += 1
                    
                    if order_type == 'limit':
                        stats['limit_order_details'].append({
                            'symbol': symbol,
                            'price': price,
                            'bid': bid,
                            'ask': ask,
                            'classification': classification
                        })

    except Exception as e:
        print(f"Error reading journal: {e}")
        return None

    return stats

def print_report(stats):
    if not stats:
        return

    print("\n" + "="*60)
    print("COINBASE MAKER ORDER AUDIT — P2-001F")
    print("="*60)
    print(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total live exploration entries analyzed: {stats['total_entries']}")
    
    print("\n1. ORDER TYPE DISTRIBUTION")
    print("-" * 30)
    for otype, count in stats['order_types'].items():
        print(f"  {otype.upper():10}: {count}")

    print("\n2. PRICING CLASSIFICATION (PROXY FOR MAKER/TAKER)")
    print("-" * 30)
    for cls, count in stats['classifications'].items():
        pct = (count / stats['total_entries'] * 100) if stats['total_entries'] > 0 else 0
        print(f"  {cls.replace('_', ' ').title():15}: {count} ({pct:5.1f}%)")

    print("\n3. ESTIMATED FEE TIER (IF PRICING PROXY HOLDS)")
    print("-" * 30)
    maker_count = stats['classifications']['likely_maker']
    taker_count = stats['classifications']['likely_taker']
    unknown_count = stats['classifications']['unknown']
    
    print(f"  Likely Maker-Priced (0.6%): {maker_count}")
    print(f"  Likely Taker-Priced (1.2%): {taker_count}")
    print(f"  Unknown                   : {unknown_count}")
    
    print("\n4. ESTIMATED ROUND-TRIP BREAK-EVEN")
    print("-" * 30)
    if maker_count > 0:
        print(f"  Likely maker-priced entries break-even: ~1.2% gross move")
    if taker_count > 0:
        print(f"  Likely taker-priced entries break-even: ~2.4% gross move")

    print("\n5. PASSIVE PRICING PERFORMANCE")
    print("-" * 30)
    if stats['order_types'].get('limit', 0) > 0:
        limit_count = stats['order_types']['limit']
        maker_pct = (maker_count / limit_count * 100) if limit_count > 0 else 0
        print(f"  Limit orders achieving likely passive-priced entries: {maker_pct:5.1f}%")
        if maker_pct > 90:
            print("  STATUS: passive_limit_entries appears to be achieving passive pricing.")
        elif maker_pct > 50:
            print("  STATUS: passive_limit_entries is working, but some fills are aggressive.")
        else:
            print("  STATUS: WARNING - most limit orders are landing with aggressive pricing.")
    else:
        print("  STATUS: No limit orders found. passive_limit_entries may be disabled or bypassed.")

    print("\n6. PER-SYMBOL BREAKDOWN")
    print("-" * 30)
    for symbol in sorted(stats['by_symbol'].keys()):
        sdata = stats['by_symbol'][symbol]
        m_count = sdata['classifications']['likely_maker']
        total = sdata['total']
        m_pct = (m_count / total * 100) if total > 0 else 0
        print(f"  {symbol:10}: {total} entries, {m_pct:5.1f}% likely maker-priced")

    print("\n7. LIMITATIONS")
    print("-" * 30)
    print("  - Journal contains BUY PLACED rows and quote context, but does not contain")
    print("    definitive Coinbase maker/taker liquidity flags for each fill.")
    print("    Classification is an advisory proxy, not proof of actual fee tier.")
    print("  - Audit assumes 'price' field in PLACED rows is the final fill price.")
    print("  - Audit assumes long positions only for maker/taker logic.")
    print("  - Classification is based on the quote at the time of order placement.")
    print("  - Coinbase may report final fees in its own dashboard which could differ.")
    print("  - Does not include exchange-specific 'post-only' confirmation flags.")

    print("\n" + "="*60)
    print("ADVISORY ONLY — Do not base trading decisions solely on this report.")
    print("="*60 + "\n")

if __name__ == "__main__":
    journal = "journal_coinbase_crypto.csv"
    results = run_audit(journal)
    print_report(results)
