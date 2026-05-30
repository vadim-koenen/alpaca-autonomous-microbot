# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.
"""
Unit tests for coinbase_exit_quality_report.py — P2-001E
"""

import pytest
import sys
import tempfile
import csv
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from coinbase_exit_quality_report import (
    classify_exit_reason,
    parse_journal,
    analyze_exits,
)


class TestClassifyExitReason:
    """Test exit reason classification."""
    
    def test_classify_max_hold(self):
        """Test max_hold classification."""
        assert classify_exit_reason("max hold time 90min exceeded (90.6min held)") == "max_hold"
        assert classify_exit_reason("Max Hold Time exceeded") == "max_hold"
    
    def test_classify_stop_loss(self):
        """Test stop_loss classification."""
        assert classify_exit_reason("stop loss triggered at 1.5%") == "stop_loss"
        assert classify_exit_reason("Stop Loss Hit") == "stop_loss"
        assert classify_exit_reason("stop-loss hit @ 2016.1450") == "stop_loss"
    
    def test_classify_take_profit(self):
        """Test take_profit classification."""
        assert classify_exit_reason("take profit triggered at 3%") == "take_profit"
        assert classify_exit_reason("Take Profit Reached") == "take_profit"
        assert classify_exit_reason("take-profit triggered") == "take_profit"
    
    def test_classify_other(self):
        """Test other classification."""
        assert classify_exit_reason("manual exit") == "other"
        assert classify_exit_reason("") == "other"
        assert classify_exit_reason(None) == "other"
    
    def test_classify_case_insensitive(self):
        """Test case insensitivity."""
        assert classify_exit_reason("MAX HOLD TIME EXCEEDED") == "max_hold"
        assert classify_exit_reason("Stop_Loss triggered") == "stop_loss"


class TestParseJournal:
    """Test journal parsing."""
    
    def test_parse_valid_journal(self):
        """Test parsing a valid journal with exits."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            # Header
            writer.writerow([
                'timestamp', 'mode', 'asset_class', 'symbol', 'strategy', 'action',
                'decision', 'reason', 'confidence', 'price', 'bid', 'ask',
                'spread_pct', 'notional', 'qty', 'order_type', 'order_id',
                'client_order_id', 'intent_key', 'status', 'fill_price',
                'exit_price', 'gross_pnl', 'fees_paid', 'pnl_usd', 'pnl_pct',
                'equity', 'buying_power', 'open_positions', 'daily_trade_count',
                'consecutive_losses', 'error'
            ])
            # Exit record
            writer.writerow([
                '2026-05-25T14:26:07Z', 'live', 'crypto', 'BTC/USD', 'strategy1',
                'EXIT', 'PLACED', 'max hold time 90min exceeded (90.6min held)',
                '0.0', '0.0', '0.0', '0.0', '0.0', '0.0', '6.44e-06', '',
                '', '', '', '', '77656.32', '77583.625',
                '-0.0004681558', '0.0059984714748', '-0.0064666272748', '-1.293',
                '0.0', '0.0', '0', '0', '0', ''
            ])
            temp_path = f.name
        
        try:
            exits = parse_journal(temp_path)
            assert len(exits) == 1
            assert exits[0]['symbol'] == 'BTC/USD'
            assert exits[0]['fill_price'] == 77656.32
            assert exits[0]['exit_price'] == 77583.625
            assert exits[0]['pnl_usd'] == pytest.approx(-0.0064666272748, rel=1e-5)
        finally:
            Path(temp_path).unlink()
    
    def test_parse_missing_file(self):
        """Test parsing non-existent file."""
        exits = parse_journal('/nonexistent/path/journal.csv')
        assert exits == []
    
    def test_parse_filters_non_exit_records(self):
        """Test that non-EXIT records are filtered out."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'symbol', 'action', 'decision', 'fill_price', 'exit_price',
                'pnl_usd', 'pnl_pct', 'fees_paid', 'gross_pnl', 'qty', 'reason'
            ])
            # BUY record (should be filtered)
            writer.writerow([
                '2026-05-25T14:26:07Z', 'BTC/USD', 'BUY', 'FILLED', '77656.32',
                '0.0', '0.0', '0.0', '0.0', '0.0', '6.44e-06', ''
            ])
            # EXIT record (should be included)
            writer.writerow([
                '2026-05-25T14:26:08Z', 'BTC/USD', 'EXIT', 'PLACED', '77656.32',
                '77583.625', '-0.0064666', '0.0', '0.006', '-0.0004681558', '6.44e-06', 'max hold'
            ])
            temp_path = f.name
        
        try:
            exits = parse_journal(temp_path)
            assert len(exits) == 1
            assert exits[0]['symbol'] == 'BTC/USD'  # Only EXIT record is parsed
            assert exits[0]['pnl_usd'] == pytest.approx(-0.0064666, rel=1e-5)
        finally:
            Path(temp_path).unlink()
    
    def test_parse_handles_invalid_numbers(self):
        """Test that invalid numeric fields are skipped."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'symbol', 'action', 'status', 'fill_price', 'exit_price',
                'pnl_usd', 'pnl_pct', 'fees_paid', 'gross_pnl', 'qty', 'reason'
            ])
            # Invalid numeric fields
            writer.writerow([
                '2026-05-25T14:26:07Z', 'BTC/USD', 'EXIT', 'PLACED', 'not_a_number',
                '77583.625', '-0.0064666', '0.0', '0.006', '-0.0004681558', '6.44e-06', 'max hold'
            ])
            temp_path = f.name
        
        try:
            exits = parse_journal(temp_path)
            # Invalid record should be skipped
            assert len(exits) == 0
        finally:
            Path(temp_path).unlink()


class TestAnalyzeExits:
    """Test exit analysis."""
    
    def test_analyze_empty_list(self):
        """Test analysis with no exits."""
        result = analyze_exits([])
        assert result == {}
    
    def test_analyze_exit_type_distribution(self):
        """Test exit type distribution counting."""
        exits = [
            {
                'timestamp': '2026-05-25T14:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded',
                'fill_price': 77656.32,
                'exit_price': 77583.625,
                'pnl_usd': -0.0064666,
                'pnl_pct': -1.293,
                'fees_paid': 0.006,
                'gross_pnl': -0.0004681558,
                'qty': 6.44e-06,
            },
            {
                'timestamp': '2026-05-25T15:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded',
                'fill_price': 77656.32,
                'exit_price': 77583.625,
                'pnl_usd': -0.0064666,
                'pnl_pct': -1.293,
                'fees_paid': 0.006,
                'gross_pnl': -0.0004681558,
                'qty': 6.44e-06,
            },
        ]
        result = analyze_exits(exits)
        
        assert result['total_exits'] == 2
        assert 'max_hold' in result['exit_type_stats']
        assert result['exit_type_stats']['max_hold']['count'] == 2
    
    def test_analyze_average_pnl(self):
        """Test average P/L calculation by exit type."""
        exits = [
            {
                'timestamp': '2026-05-25T14:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded',
                'fill_price': 77656.32,
                'exit_price': 77583.625,
                'pnl_usd': 0.01,
                'pnl_pct': 1.0,
                'fees_paid': 0.006,
                'gross_pnl': 0.01,
                'qty': 6.44e-06,
            },
            {
                'timestamp': '2026-05-25T15:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded',
                'fill_price': 77656.32,
                'exit_price': 77583.625,
                'pnl_usd': -0.01,
                'pnl_pct': -1.0,
                'fees_paid': 0.006,
                'gross_pnl': -0.01,
                'qty': 6.44e-06,
            },
        ]
        result = analyze_exits(exits)
        
        avg_pnl = result['exit_type_stats']['max_hold']['avg_pnl']
        assert avg_pnl == pytest.approx(0.0, abs=1e-10)
    
    def test_analyze_per_symbol(self):
        """Test per-symbol breakdown."""
        exits = [
            {
                'timestamp': '2026-05-25T14:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded',
                'fill_price': 77656.32,
                'exit_price': 77583.625,
                'pnl_usd': -0.01,
                'pnl_pct': -1.0,
                'fees_paid': 0.006,
                'gross_pnl': -0.01,
                'qty': 6.44e-06,
            },
            {
                'timestamp': '2026-05-25T14:26:08Z',
                'symbol': 'ETH/USD',
                'reason': 'max hold time 90min exceeded',
                'fill_price': 2117.265,
                'exit_price': 2122.705,
                'pnl_usd': 0.015,
                'pnl_pct': 0.5,
                'fees_paid': 0.0074,
                'gross_pnl': 0.01,
                'qty': 0.002923447,
            },
        ]
        result = analyze_exits(exits)
        
        assert 'BTC/USD' in result['symbol_stats']
        assert 'ETH/USD' in result['symbol_stats']
        assert result['symbol_stats']['BTC/USD']['count'] == 1
        assert result['symbol_stats']['ETH/USD']['count'] == 1
        assert result['symbol_stats']['BTC/USD']['positive_count'] == 0
        assert result['symbol_stats']['ETH/USD']['positive_count'] == 1
    
    def test_analyze_100pct_max_hold_detection(self):
        """Test that 100% max_hold is detected."""
        exits = [
            {
                'timestamp': '2026-05-25T14:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded (90.6min held)',
                'fill_price': 77656.32,
                'exit_price': 77583.625,
                'pnl_usd': -0.01,
                'pnl_pct': -1.0,
                'fees_paid': 0.006,
                'gross_pnl': -0.01,
                'qty': 6.44e-06,
            },
        ]
        result = analyze_exits(exits)
        
        # Check that max_hold count equals total exits
        assert result['exit_type_stats']['max_hold']['count'] == result['total_exits']
    
    def test_analyze_mfe_records(self):
        """Test MFE/MAE calculation."""
        exits = [
            {
                'timestamp': '2026-05-25T14:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded',
                'fill_price': 100.0,
                'exit_price': 102.0,  # +2% move
                'pnl_usd': 0.02,
                'pnl_pct': 2.0,
                'fees_paid': 0.006,
                'gross_pnl': 0.02,
                'qty': 0.01,
            },
            {
                'timestamp': '2026-05-25T15:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded',
                'fill_price': 100.0,
                'exit_price': 98.0,  # -2% move
                'pnl_usd': -0.02,
                'pnl_pct': -2.0,
                'fees_paid': 0.006,
                'gross_pnl': -0.02,
                'qty': 0.01,
            },
        ]
        result = analyze_exits(exits)
        
        assert len(result['mfe_records']) == 2
        assert result['mfe_records'][0]['mfe_pct'] == pytest.approx(2.0, rel=1e-5)
        assert result['mfe_records'][1]['mfe_pct'] == 0.0
        
        assert len(result['mae_records']) == 2
        assert result['mae_records'][0]['mae_pct'] == 0.0
        assert result['mae_records'][1]['mae_pct'] == pytest.approx(2.0, rel=1e-5)
    
    def test_analyze_hold_time_parsing(self):
        """Test parsing of hold times from reason strings."""
        exits = [
            {
                'timestamp': '2026-05-25T14:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold time 90min exceeded (90.6min held)',
                'fill_price': 100.0,
                'exit_price': 102.0,
                'pnl_usd': 0.02,
                'pnl_pct': 2.0,
                'fees_paid': 0.006,
                'gross_pnl': 0.02,
                'qty': 0.01,
            }
        ]
        result = analyze_exits(exits)
        assert result['hold_time_estimable'] is True
        assert len(result['hold_times']) == 1
        assert result['hold_times'][0] == 90.6
    
    def test_analyze_within_50pct_tp(self):
        """Test count of trades within 50% of 3% TP threshold."""
        exits = [
            {
                'timestamp': '2026-05-25T14:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold',
                'fill_price': 100.0,
                'exit_price': 102.0,
                'pnl_usd': 0.02,
                'pnl_pct': 2.0,  # Above 1.5% threshold
                'fees_paid': 0.006,
                'gross_pnl': 0.02,
                'qty': 0.01,
            },
            {
                'timestamp': '2026-05-25T15:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold',
                'fill_price': 100.0,
                'exit_price': 100.5,
                'pnl_usd': 0.005,
                'pnl_pct': 0.5,  # Below 1.5% threshold
                'fees_paid': 0.006,
                'gross_pnl': 0.005,
                'qty': 0.01,
            },
        ]
        result = analyze_exits(exits)
        
        assert result['within_50pct_tp'] == 1
    
    def test_analyze_would_trigger_sl(self):
        """Test count of exits that would trigger 1.5% SL."""
        exits = [
            {
                'timestamp': '2026-05-25T14:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold',
                'fill_price': 100.0,
                'exit_price': 98.5,
                'pnl_usd': -0.015,
                'pnl_pct': -1.5,  # Would trigger 1.5% SL
                'fees_paid': 0.006,
                'gross_pnl': -0.015,
                'qty': 0.01,
            },
            {
                'timestamp': '2026-05-25T15:26:07Z',
                'symbol': 'BTC/USD',
                'reason': 'max hold',
                'fill_price': 100.0,
                'exit_price': 99.0,
                'pnl_usd': -0.01,
                'pnl_pct': -1.0,  # Would NOT trigger 1.5% SL
                'fees_paid': 0.006,
                'gross_pnl': -0.01,
                'qty': 0.01,
            },
        ]
        result = analyze_exits(exits)
        
        assert result['would_trigger_15pct_sl'] == 1


class TestNoForbiddenImports:
    """Ensure coinbase_exit_quality_report does not import forbidden modules."""
    
    def test_no_broker_import(self):
        """Check that broker modules are not imported."""
        import coinbase_exit_quality_report as module
        forbidden = ['broker', 'broker_alpaca', 'broker_coinbase', 'order_manager',
                     'risk_manager', 'main']
        for name in dir(module):
            obj = getattr(module, name)
            for forbidden_module in forbidden:
                assert not hasattr(obj, forbidden_module), \
                    f"Forbidden import detected: {forbidden_module}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
