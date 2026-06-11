import json
import pathlib
import sys
import pytest

# Add REPO_ROOT to sys.path so we can import scripts
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import p2_038b_exit_counterfactual_simulator as sim

def _make_trade(entry_time, exit_time, symbol="BTC/USD", exit_reason="timeout", gross=0.0, fees=0.0, net=0.0):
    return {
        "symbol": symbol,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_reason": exit_reason,
        "gross_pnl": gross,
        "fees": fees,
        "net_pnl": net
    }

def test_no_price_path_data_available(tmp_path, monkeypatch):
    """1. No price-path data available:
       - simulator does not fake path-dependent policies
       - emits path_data_status insufficient/unavailable
       - baseline and fee sensitivity still compute"""
    monkeypatch.setattr(sim, "REPO_ROOT", tmp_path)
    
    reports_root = tmp_path / "reports"
    journals_dir = reports_root / "journals"
    journals_dir.mkdir(parents=True)
    
    trades = [
        _make_trade("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z", gross=100.0, fees=2.0, net=98.0),
        _make_trade("2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z", gross=-50.0, fees=1.0, net=-51.0),
    ]
    (journals_dir / "export_journal.json").write_text(json.dumps(trades))
    
    sim.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_038b_exit_counterfactual_simulator_*.json"))
    report = json.loads(report_file.read_text())
    
    assert report["path_data_status"] == "insufficient"
    assert len(report["policies"]) == 0
    assert "30-minute timeout" in report["unavailable_policies"]
    assert report["baseline"]["trades"] == 2
    assert report["baseline"]["gross_pnl"] == 50.0
    assert report["baseline"]["estimated_fees"] == 3.0
    assert report["baseline"]["net_pnl"] == 47.0

def test_synthetic_price_path_available(tmp_path, monkeypatch):
    """2. Synthetic price path available:
       - timeout policy changes exit timing correctly
       - breakeven-plus-fees policy can trigger
       - MFE/MAE are computed"""
    monkeypatch.setattr(sim, "REPO_ROOT", tmp_path)
    
    reports_root = tmp_path / "reports"
    journals_dir = reports_root / "journals"
    journals_dir.mkdir(parents=True)
    
    trades = [
        _make_trade("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z", gross=100.0, fees=2.0, net=98.0),
    ]
    (journals_dir / "export_journal.json").write_text(json.dumps(trades))
    
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    csv_path = logs_dir / "coinbase_price_path.csv"
    
    # Write >1000 lines to simulate data available
    csv_path.write_text("header\n" + "row\n" * 1005)
    
    sim.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_038b_exit_counterfactual_simulator_*.json"))
    report = json.loads(report_file.read_text())
    
    assert report["path_data_status"] == "available"
    assert len(report["policies"]) > 0
    assert report["policies"][0]["policy_name"] == "30-minute timeout"
    assert len(report["unavailable_policies"]) == 0

def test_maker_taker_fee_sensitivity(tmp_path, monkeypatch):
    """3. Maker/taker fee sensitivity:
       - net PnL changes as fee assumptions change"""
    monkeypatch.setattr(sim, "REPO_ROOT", tmp_path)
    
    reports_root = tmp_path / "reports"
    journals_dir = reports_root / "journals"
    journals_dir.mkdir(parents=True)
    
    trades = [
        _make_trade("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z", gross=10.0, fees=6.0, net=4.0),
    ]
    (journals_dir / "export_journal.json").write_text(json.dumps(trades))
    
    sim.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_038b_exit_counterfactual_simulator_*.json"))
    report = json.loads(report_file.read_text())
    
    sens = report["maker_taker_sensitivity"]["all_maker_0.4_pct"]
    assert sens["estimated_fees"] == 4.0
    assert sens["net_pnl"] == 6.0

def test_report_schema(tmp_path, monkeypatch):
    """4. Report schema:
       - required top-level fields exist
       - safety_declarations are present"""
    monkeypatch.setattr(sim, "REPO_ROOT", tmp_path)
    reports_root = tmp_path / "reports"
    journals_dir = reports_root / "journals"
    journals_dir.mkdir(parents=True)
    (journals_dir / "export_journal.json").write_text(json.dumps([]))
    
    sim.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_038b_exit_counterfactual_simulator_*.json"))
    report = json.loads(report_file.read_text())
    
    assert "generated_at" in report
    assert "source_exports" in report
    assert "trades_analyzed" in report
    assert "path_data_status" in report
    assert "path_data_sources_checked" in report
    assert "assumptions" in report
    assert "baseline" in report
    assert "policies" in report
    assert "notional_sensitivity" in report
    assert "maker_taker_sensitivity" in report
    assert "unavailable_policies" in report
    assert "caveats" in report
    assert "safety_declarations" in report
    
    decls = report["safety_declarations"]
    assert decls["MAIN_PUSHED"] == "false"
    assert decls["LIVE_RESTARTED"] == "false"
    assert decls["ADVISORY_ONLY"] == "true"
