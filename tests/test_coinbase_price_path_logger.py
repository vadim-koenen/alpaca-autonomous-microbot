# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Unit tests for coinbase_price_path_logger.py — P2-003
"""

import json
import csv
import pytest
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from coinbase_price_path_logger import fetch_spot_price, parse_iso_timestamp, main, OPEN_POSITIONS_PATH, LOG_PATH

def test_symbol_conversion():
    symbol = "BTC/USD"
    product_id = symbol.replace('/', '-')
    assert product_id == "BTC-USD"

def test_unrealized_pct():
    entry_price = 100.0
    current_price = 105.0
    pct = (current_price - entry_price) / entry_price * 100
    assert pct == 5.0

def test_hold_minutes():
    now = datetime.now(timezone.utc)
    entry_time = now - timedelta(minutes=45)
    td = now - entry_time
    minutes = round(td.total_seconds() / 60, 2)
    assert minutes == 45.0

def test_parse_iso_timestamp():
    ts = "2026-05-30T10:00:00Z"
    dt = parse_iso_timestamp(ts)
    assert dt == datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)
    
    ts2 = "2026-05-30T10:00:00.123456+00:00"
    dt2 = parse_iso_timestamp(ts2)
    assert dt2.hour == 10
    assert dt2.minute == 0

@patch('urllib.request.urlopen')
def test_fetch_spot_price_success(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "data": {"base": "BTC", "currency": "USD", "amount": "75000.50"}
    }).encode()
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response
    
    price = fetch_spot_price("BTC-USD")
    assert price == 75000.50

@patch('urllib.request.urlopen')
def test_fetch_spot_price_error(mock_urlopen):
    mock_urlopen.side_effect = Exception("API Down")
    price = fetch_spot_price("BTC-USD")
    assert price is None

def test_no_open_positions(tmp_path):
    state_file = tmp_path / "open_positions.json"
    state_file.write_text(json.dumps({"positions": {}}))
    
    with patch('coinbase_price_path_logger.OPEN_POSITIONS_PATH', state_file):
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 0

def test_qualifying_positions_filtering(tmp_path):
    state_file = tmp_path / "open_positions.json"
    state_file.write_text(json.dumps({
        "positions": {
            "BTC/USD": {"strategy": "coinbase_exploration", "entry_price": 70000, "entry_time": "2026-05-30T10:00:00Z"},
            "ETH/USD": {"strategy": "other", "entry_price": 2000, "entry_time": "2026-05-30T10:00:00Z"}
        }
    }))
    
    log_file = tmp_path / "coinbase_price_path.csv"
    
    with patch('coinbase_price_path_logger.OPEN_POSITIONS_PATH', state_file), \
         patch('coinbase_price_path_logger.LOG_PATH', log_file), \
         patch('coinbase_price_path_logger.fetch_spot_price', return_value=71000.0):
        main()
        
    assert log_file.exists()
    with open(log_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]['symbol'] == "BTC/USD"

def test_list_shaped_positions(tmp_path):
    state_file = tmp_path / "open_positions.json"
    state_file.write_text(json.dumps({
        "positions": [
            {"symbol": "SOL/USD", "strategy": "coinbase_exploration", "entry_price": 80, "entry_time": "2026-05-30T10:00:00Z"}
        ]
    }))
    
    log_file = tmp_path / "coinbase_price_path.csv"
    
    with patch('coinbase_price_path_logger.OPEN_POSITIONS_PATH', state_file), \
         patch('coinbase_price_path_logger.LOG_PATH', log_file), \
         patch('coinbase_price_path_logger.fetch_spot_price', return_value=82.0):
        main()
        
    assert log_file.exists()
    with open(log_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]['symbol'] == "SOL/USD"

def test_skips_invalid_entry_price(tmp_path):
    state_file = tmp_path / "open_positions.json"
    state_file.write_text(json.dumps({
        "positions": {
            "BTC/USD": {"strategy": "coinbase_exploration", "entry_price": "invalid", "entry_time": "2026-05-30T10:00:00Z"}
        }
    }))
    
    log_file = tmp_path / "coinbase_price_path.csv"
    
    with patch('coinbase_price_path_logger.OPEN_POSITIONS_PATH', state_file), \
         patch('coinbase_price_path_logger.LOG_PATH', log_file):
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 0
    assert not log_file.exists()

def test_no_forbidden_imports():
    import coinbase_price_path_logger as module
    forbidden = ['broker', 'order_manager', 'risk_manager', 'main']
    for name in dir(module):
        if name == 'main': continue
        assert name not in forbidden

if __name__ == "__main__":
    pytest.main([__file__, '-v'])
