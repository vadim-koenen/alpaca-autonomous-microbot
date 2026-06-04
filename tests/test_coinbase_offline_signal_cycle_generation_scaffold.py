import json
from pathlib import Path
from scripts.coinbase_offline_signal_cycle_generation_scaffold import build_offline_signal_scaffold

def test_scaffold_inventory_detection(tmp_path):
    data_dir = tmp_path / "ohlcv"
    data_dir.mkdir()
    
    # Create dummy csv
    csv_file = data_dir / "BTC-USD_5m_2026-01-01_2026-01-01.csv"
    csv_file.write_text("timestamp_utc,o,h,l,c,v\n2026-01-01T00:00:00Z,100,105,95,102,10\n", encoding="utf-8")
    
    payload = build_offline_signal_scaffold(data_dir=data_dir)
    
    assert len(payload["ohlcv_inventory"]) == 1
    assert payload["ohlcv_inventory"][0]["symbol"] == "BTC/USD"
    assert payload["ohlcv_inventory"][0]["candle_count"] == 1

def test_readiness_gates_false_by_default(tmp_path):
    payload = build_offline_signal_scaffold(data_dir=tmp_path)
    assert payload["readiness"]["signal_generation_ready"] is False
    assert payload["readiness"]["cycle_generation_ready"] is False
    assert payload["readiness"]["historical_backtest_ready"] is False

def test_json_schema(tmp_path):
    payload = build_offline_signal_scaffold(data_dir=tmp_path)
    for key in ["ohlcv_inventory", "required_signal_inputs", "missing_components", "readiness", "proposed_architecture", "verdict"]:
        assert key in payload
    assert payload["verdict"]["implementation_authorized"] is False

def test_safety_and_no_mutation(tmp_path):
    payload = build_offline_signal_scaffold(data_dir=tmp_path)
    text = json.dumps(payload).lower()
    for phrase in ["create_order", "place_order", ".env", "api_key"]:
        assert phrase not in text
