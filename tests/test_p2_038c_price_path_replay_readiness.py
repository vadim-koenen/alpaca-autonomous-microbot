import json
import pathlib
import sys
import pytest

# Add REPO_ROOT to sys.path so we can import scripts
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import p2_038c_price_path_replay_readiness as readiness

def _make_trade(entry_time, exit_time, symbol="BTC/USD", exit_reason="timeout"):
    return {
        "symbol": symbol,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_reason": exit_reason
    }

def test_no_local_path_data_available(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness, "REPO_ROOT", tmp_path)
    reports_root = tmp_path / "reports"
    journals_dir = reports_root / "journals"
    journals_dir.mkdir(parents=True)
    
    trades = [_make_trade("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")]
    (journals_dir / "export_journal.json").write_text(json.dumps(trades))
    
    # Do not create any log file
    readiness.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_038c_price_path_replay_readiness_*.json"))
    report = json.loads(report_file.read_text())
    
    assert report["REPLAY_READY"] is False
    assert report["readiness_summary"]["trades_missing"] == 1
    assert report["public_ohlcv_feasibility"]["network_call_made"] is False
    assert "public OHLCV backfill or safe passive path capture design" in report["next_required_actions"]

def test_sparse_path_data_partial_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness, "REPO_ROOT", tmp_path)
    reports_root = tmp_path / "reports"
    journals_dir = reports_root / "journals"
    journals_dir.mkdir(parents=True)
    
    trades = [_make_trade("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")]
    (journals_dir / "export_journal.json").write_text(json.dumps(trades))
    
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    csv_path = logs_dir / "coinbase_price_path.csv"
    csv_path.write_text("header\n" + "row\n" * 15) # > 10 rows but < 1000
    
    readiness.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_038c_price_path_replay_readiness_*.json"))
    report = json.loads(report_file.read_text())
    
    assert report["REPLAY_READY"] is False
    assert report["readiness_summary"]["trades_partial"] == 1
    
    tr_readiness = report["per_trade_readiness"][0]
    assert tr_readiness["readiness_status"] == "partial"
    # Testing that gap detection/fields exist
    assert "gaps_count" in tr_readiness
    assert "max_gap_seconds" in tr_readiness

def test_complete_synthetic_path_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness, "REPO_ROOT", tmp_path)
    reports_root = tmp_path / "reports"
    journals_dir = reports_root / "journals"
    journals_dir.mkdir(parents=True)
    
    trades = [_make_trade("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")]
    (journals_dir / "export_journal.json").write_text(json.dumps(trades))
    
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    csv_path = logs_dir / "coinbase_price_path.csv"
    csv_path.write_text("header\n" + "row\n" * 1005) # > 1000 rows
    
    readiness.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_038c_price_path_replay_readiness_*.json"))
    report = json.loads(report_file.read_text())
    
    assert report["REPLAY_READY"] is True
    assert report["readiness_summary"]["trades_ready"] == 1
    
    tr_readiness = report["per_trade_readiness"][0]
    assert tr_readiness["readiness_status"] == "ready"
    assert tr_readiness["required_window_start"] == "2026-06-01T10:00:00Z"

def test_report_schema_and_safety_declarations(tmp_path, monkeypatch):
    monkeypatch.setattr(readiness, "REPO_ROOT", tmp_path)
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    
    readiness.main()
    
    diag_dir = reports_root / "diagnostics"
    report_file = next(diag_dir.glob("p2_038c_price_path_replay_readiness_*.json"))
    report = json.loads(report_file.read_text())
    
    assert "safety_declarations" in report
    decls = report["safety_declarations"]
    assert decls["MAIN_PUSHED"] == "false"
    assert decls["LIVE_RESTARTED"] == "false"
    assert decls["ADVISORY_ONLY"] == "true"
