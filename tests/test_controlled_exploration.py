import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import csv
import os

from strategy_crypto import CryptoStrategy
from market_data import MarketData

def test_exploration_single_proposal_per_cycle(monkeypatch, tmp_path):
    """Test that only one proposal is made per scan cycle (cycle flag)."""
    md = MagicMock(spec=MarketData)
    
    # Create a temporary journal file (empty)
    journal_file = tmp_path / "journal_test.csv"
    with open(journal_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "symbol", "strategy", "decision"])
        writer.writeheader()
    
    config = {
        "crypto": {
            "controlled_exploration": {
                "enabled": True,
                "approved_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
                "max_single_trade_notional_usd": 1.00,
                "per_symbol_cooldown_minutes": 0,
                "max_entries_per_symbol_per_day": 4,
            },
            "live_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
        },
        "logging": {"journal_file": str(journal_file)}
    }

    def mock_get_cfg(*keys, default=None):
        val = config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val
    
    import strategy_crypto
    monkeypatch.setattr(strategy_crypto, "get_cfg", mock_get_cfg)
    monkeypatch.setattr(strategy_crypto, "load_saved_positions", lambda: {})
    monkeypatch.setattr(strategy_crypto, "ROOT", tmp_path)

    strategy = CryptoStrategy(md)
    
    quote = MagicMock()
    quote.bid = 100.0
    quote.ask = 100.1
    quote.mid = 100.05
    quote.timestamp = datetime.now(timezone.utc)
    
    df = pd.DataFrame({"c": [100.0] * 100}, index=pd.date_range("2020-01-01", periods=100))
    
    # First call: Should select BTC (first eligible when all equally eligible)
    proposal = strategy._coinbase_exploration("BTC/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is not None
    assert proposal.symbol == "BTC/USD"
    
    # Simulate journal update: add BTC entry
    with open(journal_file, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "symbol", "strategy", "decision"])
        writer.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": "BTC/USD",
            "strategy": "coinbase_exploration",
            "decision": "FILLED"
        })
    
    # Same cycle: ETH/USD is skipped because self._exploration_proposed_this_cycle is True
    proposal = strategy._coinbase_exploration("ETH/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is None

    # Reset for new cycle
    strategy._exploration_proposed_this_cycle = False
    
    # Next cycle: ETH/USD should be selected (BTC is in history, so least-recent is ETH/SOL)
    proposal = strategy._coinbase_exploration("ETH/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is not None
    assert proposal.symbol == "ETH/USD"

def test_exploration_symbol_selection_with_open_positions(monkeypatch, tmp_path):
    """Test that symbols with open positions are avoided."""
    md = MagicMock(spec=MarketData)
    
    journal_file = tmp_path / "journal_test.csv"
    with open(journal_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "symbol", "strategy", "decision"])
        writer.writeheader()
    
    config = {
        "crypto": {
            "controlled_exploration": {
                "enabled": True,
                "approved_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
                "max_single_trade_notional_usd": 1.00,
                "per_symbol_cooldown_minutes": 0,
                "max_entries_per_symbol_per_day": 4,
            },
            "live_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
        },
        "logging": {"journal_file": str(journal_file)}
    }

    def mock_get_cfg(*keys, default=None):
        val = config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val
    
    import strategy_crypto
    monkeypatch.setattr(strategy_crypto, "get_cfg", mock_get_cfg)
    
    # Mock open positions: BTC/USD has an open position
    def mock_load_positions():
        return {"BTC/USD": {"entry_price": 100.0, "qty": 0.01}}
    
    monkeypatch.setattr(strategy_crypto, "load_saved_positions", mock_load_positions)
    monkeypatch.setattr(strategy_crypto, "ROOT", tmp_path)

    strategy = CryptoStrategy(md)
    
    quote = MagicMock()
    quote.bid = 100.0
    quote.ask = 100.1
    quote.mid = 100.05
    quote.timestamp = datetime.now(timezone.utc)
    
    df = pd.DataFrame({"c": [100.0] * 100}, index=pd.date_range("2020-01-01", periods=100))
    
    # When we scan BTC/USD, it should NOT be selected (has open position)
    # So if ETH/USD symbol parameter comes first, it should be proposed
    proposal = strategy._coinbase_exploration("ETH/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is not None
    assert proposal.symbol == "ETH/USD"
