import pytest
from unittest.mock import MagicMock
import pandas as pd
from datetime import datetime, timezone

from strategy_crypto import CryptoStrategy
from market_data import MarketData

def test_exploration_rotation_logic(monkeypatch):
    # Mock MarketData
    md = MagicMock(spec=MarketData)
    
    # Configuration for exploration
    config = {
        "crypto": {
            "controlled_exploration": {
                "enabled": True,
                "approved_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
                "max_single_trade_notional_usd": 1.00,
                "per_symbol_cooldown_minutes": 0,  # No cooldown for test
            },
            "live_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"]
        }
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

    strategy = CryptoStrategy(md)
    
    # Mock market data
    quote = MagicMock()
    quote.bid = 100.0
    quote.ask = 100.1
    quote.mid = 100.05
    quote.timestamp = datetime.now(timezone.utc)
    
    df = pd.DataFrame({"c": [100.0] * 100}, index=pd.date_range("2020-01-01", periods=100))
    
    # First call: target is BTC/USD
    proposal = strategy._coinbase_exploration("BTC/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is not None
    assert proposal.symbol == "BTC/USD"
    assert strategy._exploration_index == 1
    
    # Same cycle: ETH/USD is skipped because self._exploration_proposed_this_cycle is True
    proposal = strategy._coinbase_exploration("ETH/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is None

    # Reset for new cycle
    strategy._exploration_proposed_this_cycle = False
    
    # Now it's ETH/USD's turn
    proposal = strategy._coinbase_exploration("BTC/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is None # BTC is skipped, it's ETH's turn
    
    proposal = strategy._coinbase_exploration("ETH/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is not None
    assert proposal.symbol == "ETH/USD"
    assert strategy._exploration_index == 2

def test_exploration_cooldown(monkeypatch):
    md = MagicMock(spec=MarketData)
    config = {
        "crypto": {
            "controlled_exploration": {
                "enabled": True,
                "approved_symbols": ["BTC/USD"],
                "per_symbol_cooldown_minutes": 30,
            },
            "live_symbols": ["BTC/USD"]
        }
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
    strategy = CryptoStrategy(md)
    df = pd.DataFrame({"c": [100.0] * 100}, index=pd.date_range("2020-01-01", periods=100))
    quote = MagicMock()
    quote.bid = 100.0
    quote.ask = 100.1
    quote.mid = 100.05
    quote.timestamp = datetime.now(timezone.utc)

    # First trade
    proposal = strategy._coinbase_exploration("BTC/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is not None
    
    # Second trade immediately after (resetting cycle flag)
    strategy._exploration_proposed_this_cycle = False
    proposal = strategy._coinbase_exploration("BTC/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is None # Blocked by cooldown
