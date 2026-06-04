import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd
from scripts.coinbase_offline_strategy_runner_adapter import build_strategy_runner_report, OfflineMarketDataAdapter, _model_quote_from_bar

def test_adapter_marketdata_mock():
    df = pd.DataFrame({"c": [100, 101, 102]})
    from market_data import Quote
    quote = Quote(symbol="BTC/USD", bid=101.9, ask=102.1, mid=102.0, spread_pct=0.2, timestamp=None, is_stale=False)
    
    adapter = OfflineMarketDataAdapter(df, quote)
    
    assert adapter.get_crypto_quote("BTC/USD") == quote
    assert len(adapter.get_crypto_bars_df("BTC/USD", limit=2)) == 2
    assert adapter.get_crypto_bars_df("BTC/USD", limit=2).iloc[-1]["c"] == 102

def test_model_quote_from_bar():
    class FakeBar:
        def __init__(self, t, c):
            self.t = t
            self.c = c
    
    bar = FakeBar(t=None, c=1000.0)
    quote = _model_quote_from_bar(bar, spread_pct=0.10)
    
    assert quote.mid == 1000.0
    # spread 0.10% of 1000 is 1.0. half is 0.5.
    assert quote.bid == 999.5
    assert quote.ask == 1000.5

def test_strategy_runner_report_schema(tmp_path):
    # Empty data dir
    payload = build_strategy_runner_report(data_dir=tmp_path)
    
    for key in ["strategy_logic_importable", "offline_strategy_runner_ready", "historical_signal_generation_ready", "available_reusable_functions", "smoke_run", "verdict"]:
        assert key in payload
    assert payload["verdict"]["implementation_authorized"] is False

def test_readiness_with_synthetic_fixture(tmp_path):
    data_dir = tmp_path / "ohlcv"
    data_dir.mkdir()
    
    # Create dummy csv for BTC/USD
    csv_file = data_dir / "BTC-USD_5m_2026-01-01_2026-01-01.csv"
    csv_file.write_text("timestamp_utc,o,h,l,c,v\n2026-01-01T00:00:00Z,100,105,95,102,10\n", encoding="utf-8")
    
    # We need to mock strategy_crypto imports if they fail, but in this repo they should succeed.
    payload = build_strategy_runner_report(data_dir=data_dir, symbol="BTC/USD")
    
    assert payload["smoke_run"]["bars_loaded"] == 1
    # Signals count might be 0 or more depending on logic, but shouldn't crash
    assert payload["strategy_logic_importable"] is True

def test_safety_and_no_mutation(tmp_path):
    payload = build_strategy_runner_report(data_dir=tmp_path)
    text = json.dumps(payload).lower()
    for phrase in ["create_order", "place_order", ".env", "api_key"]:
        assert phrase not in text
