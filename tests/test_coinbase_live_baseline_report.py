# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Unit tests for coinbase_live_baseline_report.py — P2-001H
"""

import pytest
import sys
import tempfile
import csv
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from coinbase_live_baseline_report import (
    classify_exit_reason,
    parse_hold_time,
    run_baseline_report,
)

def test_classify_exit_reason():
    assert classify_exit_reason("max hold time exceeded") == "max_hold"
    assert classify_exit_reason("stop loss triggered") == "stop_loss"
    assert classify_exit_reason("stop-loss hit") == "stop_loss"
    assert classify_exit_reason("take profit reached") == "take_profit"
    assert classify_exit_reason("take-profit triggered") == "take_profit"
    assert classify_exit_reason("manual exit") == "other"
    assert classify_exit_reason(None) == "other"

def test_parse_hold_time():
    assert parse_hold_time("max hold time (90.6min held)") == 90.6
    assert parse_hold_time("exit (45.0min held)") == 45.0
    assert parse_hold_time("no hold time") is None
    assert parse_hold_time(None) is None

def test_filtering_logic():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'mode', 'asset_class', 'symbol', 'strategy', 'action',
            'decision', 'reason', 'fill_price', 'exit_price', 'gross_pnl',
            'fees_paid', 'pnl_usd', 'pnl_pct'
        ])
        writer.writeheader()
        # Qualifying row
        writer.writerow({
            'mode': 'live', 'strategy': 'coinbase_exploration', 'symbol': 'BTC/USD',
            'action': 'EXIT', 'decision': 'FILLED', 'reason': 'max hold',
            'fill_price': '100', 'exit_price': '101', 'gross_pnl': '1',
            'fees_paid': '0.1', 'pnl_usd': '0.9', 'pnl_pct': '1'
        })
        # Wrong mode
        writer.writerow({
            'mode': 'dry_run', 'strategy': 'coinbase_exploration', 'symbol': 'BTC/USD',
            'action': 'EXIT', 'decision': 'FILLED'
        })
        # Wrong strategy
        writer.writerow({
            'mode': 'live', 'strategy': 'coinbase_probe', 'symbol': 'BTC/USD',
            'action': 'EXIT', 'decision': 'FILLED'
        })
        # Wrong symbol
        writer.writerow({
            'mode': 'live', 'strategy': 'coinbase_exploration', 'symbol': 'ALGO/USD',
            'action': 'EXIT', 'decision': 'FILLED'
        })
        # Not an exit
        writer.writerow({
            'mode': 'live', 'strategy': 'coinbase_exploration', 'symbol': 'BTC/USD',
            'action': 'BUY', 'decision': 'FILLED'
        })
        # Failed decision
        writer.writerow({
            'mode': 'live', 'strategy': 'coinbase_exploration', 'symbol': 'BTC/USD',
            'action': 'EXIT', 'decision': 'REJECTED'
        })
        temp_path = f.name

    try:
        results = run_baseline_report(temp_path)
        assert results['total_exits'] == 1
        assert 'BTC/USD' in results['by_symbol']
        assert len(results['by_symbol']) == 1
    finally:
        Path(temp_path).unlink()

def test_empty_journal():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        writer = csv.DictWriter(f, fieldnames=['mode'])
        writer.writeheader()
        temp_path = f.name
    try:
        results = run_baseline_report(temp_path)
        assert results['total_exits'] == 0
    finally:
        Path(temp_path).unlink()

def test_no_forbidden_imports():
    import coinbase_live_baseline_report as module
    forbidden = ['broker', 'order_manager', 'risk_manager', 'main']
    for name in dir(module):
        assert name not in forbidden

if __name__ == "__main__":
    pytest.main([__file__])
