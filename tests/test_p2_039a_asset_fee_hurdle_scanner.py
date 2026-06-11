import json
import pathlib
import sys

# Add REPO_ROOT to sys.path so we can import scripts
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import p2_039a_asset_fee_hurdle_scanner as scanner

def test_hurdle_calculation_taker_maker():
    taker = scanner.calculate_hurdle(10.0, "taker")
    maker = scanner.calculate_hurdle(10.0, "maker")
    
    assert taker["notional_usd"] == 10.0
    assert taker["estimated_rt_fee_pct"] == 1.2  # 0.6 * 2 * 100
    assert maker["estimated_rt_fee_pct"] == 0.8  # 0.4 * 2 * 100
    
    assert taker["all_in_hurdle_pct"] == 1.25  # 1.2 + 0.05
    assert maker["all_in_hurdle_pct"] == 0.85  # 0.8 + 0.05
    
    assert taker["all_in_hurdle_dollars"] == 0.125
    assert maker["all_in_hurdle_dollars"] == 0.085

def test_notional_sensitivity():
    h1 = scanner.calculate_hurdle(1.0, "taker")
    h100 = scanner.calculate_hurdle(100.0, "taker")
    
    assert h1["all_in_hurdle_pct"] == h100["all_in_hurdle_pct"]
    assert h1["all_in_hurdle_dollars"] == 0.0125
    assert h100["all_in_hurdle_dollars"] == 1.25

def test_no_ohlcv_data(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "REPO_ROOT", tmp_path)
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    
    scanner.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_039a_asset_fee_hurdle_scanner_*.json"))
    report = json.loads(report_file.read_text())
    
    assert len(report["insufficient_data_assets"]) == len(report["candidate_assets"])
    
    for v in report["asset_viability"]:
        assert v["viable_for_live"] is False
        assert v["viable_for_research"] is False
        assert v["data_status"] == "missing"
        assert v["hurdle_status"] == "fail"

def test_synthetic_ohlcv_data_found(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "REPO_ROOT", tmp_path)
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    csv = logs_dir / "coinbase_price_path.csv"
    csv.write_text("header\n" + "row\n" * 150)
    
    scanner.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_039a_asset_fee_hurdle_scanner_*.json"))
    report = json.loads(report_file.read_text())
    
    assert len(report["insufficient_data_assets"]) == 0
    
    for v in report["asset_viability"]:
        assert v["viable_for_live"] is False
        assert v["viable_for_research"] is True
        assert v["data_status"] == "ready"
        assert v["hurdle_status"] == "pass"

def test_default_no_fetch_and_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "REPO_ROOT", tmp_path)
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    
    scanner.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_039a_asset_fee_hurdle_scanner_*.json"))
    report = json.loads(report_file.read_text())
    
    assert report["public_ohlcv_feasibility"]["network_call_made"] is False
    assert "safety_declarations" in report
    assert report["safety_declarations"]["LIVE_RESTARTED"] == "false"
    assert report["safety_declarations"]["ADVISORY_ONLY"] == "true"
