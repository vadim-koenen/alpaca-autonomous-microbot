# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Unit tests for coinbase_maker_order_audit.py — P2-001F
"""

import pytest
import sys
import tempfile
import csv
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from coinbase_maker_order_audit import classify_fill, run_audit

class TestMakerOrderAudit:
    def test_classify_fill_maker(self):
        # BUY at midpoint
        assert classify_fill(100.5, 100.0, 101.0) == 'likely_maker'
        # BUY at bid
        assert classify_fill(100.0, 100.0, 101.0) == 'likely_maker'
        # BUY below bid
        assert classify_fill(99.0, 100.0, 101.0) == 'likely_maker'

    def test_classify_fill_taker(self):
        # BUY at ask
        assert classify_fill(101.0, 100.0, 101.0) == 'likely_taker'
        # BUY above ask
        assert classify_fill(102.0, 100.0, 101.0) == 'likely_taker'
        # BUY between mid and ask
        assert classify_fill(100.75, 100.0, 101.0) == 'likely_taker'

    def test_classify_fill_unknown(self):
        # Missing data
        assert classify_fill(0, 100, 101) == 'unknown'
        assert classify_fill(100, 0, 101) == 'unknown'
        assert classify_fill(100, 100, 0) == 'unknown'

    def test_run_audit_empty(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(['mode', 'strategy', 'action', 'decision'])
            temp_path = f.name
        
        try:
            stats = run_audit(temp_path)
            assert stats['total_entries'] == 0
        finally:
            Path(temp_path).unlink()

    def test_run_audit_logic(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(['mode', 'strategy', 'action', 'decision', 'symbol', 'order_type', 'price', 'bid', 'ask'])
            # Maker entry
            writer.writerow(['live', 'coinbase_exploration', 'BUY', 'PLACED', 'BTC/USD', 'limit', '73128.005', '73128.0', '73128.01'])
            # Taker entry
            writer.writerow(['live', 'coinbase_exploration', 'BUY', 'PLACED', 'ETH/USD', 'limit', '2000.0', '1990.0', '2000.0'])
            # Not exploration (filtered)
            writer.writerow(['live', 'other_strat', 'BUY', 'PLACED', 'SOL/USD', 'limit', '80.0', '79.0', '81.0'])
            temp_path = f.name
        
        try:
            stats = run_audit(temp_path)
            assert stats['total_entries'] == 2
            assert stats['classifications']['likely_maker'] == 1
            assert stats['classifications']['likely_taker'] == 1
            assert stats['order_types']['limit'] == 2
            assert 'BTC/USD' in stats['by_symbol']
            assert 'ETH/USD' in stats['by_symbol']
        finally:
            Path(temp_path).unlink()

    def test_no_forbidden_imports(self):
        import coinbase_maker_order_audit as module
        forbidden = ['broker', 'broker_alpaca', 'broker_coinbase', 'order_manager',
                     'risk_manager', 'main']
        source = (Path(__file__).parent.parent / 'scripts' / 'coinbase_maker_order_audit.py').read_text(encoding='utf-8')
        for forbidden_module in forbidden:
            assert f"import {forbidden_module}" not in source
            assert f"from {forbidden_module}" not in source
        
        # Also check for explicit imports in the module namespace
        for name in dir(module):
            assert name not in forbidden

if __name__ == "__main__":
    pytest.main([__file__, '-v'])
