#!/usr/bin/env python3
# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Coinbase Intra-Hold Price Path Logger — P2-003

Captures spot price snapshots for open coinbase_exploration positions
every 60 seconds to enable true MFE/MAE analysis.
"""

import json
import csv
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

# Paths
REPO_ROOT = Path(__file__).parent.parent
OPEN_POSITIONS_PATH = REPO_ROOT / "state" / "coinbase" / "open_positions.json"
LOG_DIR = REPO_ROOT / "logs"
LOG_PATH = LOG_DIR / "coinbase_price_path.csv"

def fetch_spot_price(product_id):
    """Fetch current spot price from Coinbase public REST API."""
    url = f"https://api.coinbase.com/v2/prices/{product_id}/spot"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            return float(data['data']['amount'])
    except Exception as e:
        print(f"Warning: Failed to fetch price for {product_id}: {e}")
        return None

def parse_iso_timestamp(ts_str):
    """Parse ISO 8601 timestamp string to datetime object."""
    if not ts_str:
        return None
    try:
        # Handle 2026-05-26T16:40:07.094069+00:00 or 2026-05-26T16:40:07Z
        ts_str = ts_str.replace('Z', '+00:00')
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None

def main():
    # 1. Read open positions
    if not OPEN_POSITIONS_PATH.exists():
        # Exit silently if state file missing
        sys.exit(0)

    try:
        with open(OPEN_POSITIONS_PATH, 'r') as f:
            state = json.load(f)
    except Exception as e:
        print(f"Error reading open_positions.json: {e}")
        sys.exit(1)

    # Support dict or list of positions
    positions_raw = state.get('positions', {})
    if isinstance(positions_raw, dict):
        # If dict, use values, but keep key as potential ID
        positions = []
        for key, pos in positions_raw.items():
            if not isinstance(pos, dict): continue
            if 'symbol' not in pos: pos['symbol'] = key # Fallback
            if 'position_id' not in pos: pos['position_id'] = key
            positions.append(pos)
    else:
        positions = positions_raw

    # 2. Filter for coinbase_exploration strategy
    qualifying_positions = [
        p for p in positions 
        if isinstance(p, dict) and p.get('strategy') == 'coinbase_exploration'
    ]

    if not qualifying_positions:
        # Exit silently if no qualifying positions
        sys.exit(0)

    # 3. Ensure logs directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not LOG_PATH.exists()

    now_utc = datetime.now(timezone.utc)
    csv_rows = []

    for pos in qualifying_positions:
        symbol = pos.get('symbol', 'UNKNOWN')
        # Map fields
        entry_price = pos.get('entry_price') or pos.get('fill_price') or pos.get('avg_entry_price') or pos.get('price')
        entry_timestamp_str = pos.get('entry_time') or pos.get('entry_timestamp') or pos.get('opened_at') or pos.get('timestamp') or pos.get('created_at')
        position_id = pos.get('position_id') or pos.get('id') or pos.get('client_order_id') or f"{symbol}_{entry_timestamp_str}"

        if entry_price is None:
            print(f"Warning: Position {position_id} has no valid entry_price field. Skipping.")
            continue

        try:
            entry_price = float(entry_price)
        except (ValueError, TypeError):
            print(f"Warning: Position {position_id} has unparsable entry_price: {entry_price}. Skipping.")
            continue

        # Convert symbol to Coinbase product ID (BTC/USD -> BTC-USD)
        product_id = symbol.replace('/', '-')
        current_price = fetch_spot_price(product_id)

        if current_price is None:
            continue

        # Calculations
        unrealized_pct = (current_price - entry_price) / entry_price * 100
        
        hold_minutes = None
        entry_dt = parse_iso_timestamp(entry_timestamp_str)
        if entry_dt:
            td = now_utc - entry_dt
            hold_minutes = round(td.total_seconds() / 60, 2)

        csv_rows.append({
            'timestamp_utc': now_utc.isoformat().replace('+00:00', 'Z'),
            'symbol': symbol,
            'position_id': position_id,
            'entry_price': entry_price,
            'current_price': current_price,
            'unrealized_pct': round(unrealized_pct, 4),
            'hold_minutes': hold_minutes,
            'entry_timestamp': entry_timestamp_str
        })

    if not csv_rows:
        sys.exit(0)

    # 4. Append to CSV
    fieldnames = [
        'timestamp_utc', 'symbol', 'position_id', 'entry_price', 
        'current_price', 'unrealized_pct', 'hold_minutes', 'entry_timestamp'
    ]
    
    try:
        with open(LOG_PATH, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(csv_rows)
    except Exception as e:
        print(f"Error writing to log: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
