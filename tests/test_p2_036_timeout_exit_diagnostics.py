import json
import pathlib
import sys
import subprocess
import pytest

# Make repo root importable for the script
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT))

from scripts import p2_036_timeout_exit_diagnostics as diag

def _make_entry(reason, gross=0.0, fees=0.0, net=0.0, entry_time=None, exit_time=None, mfe=None, mae=None):
    e = {"exit_reason": reason, "gross_pnl": gross, "fees": fees, "net_pnl": net}
    if entry_time:
        e["entry_time"] = entry_time
    if exit_time:
        e["exit_time"] = exit_time
    if mfe is not None:
        e["mfe"] = mfe
    if mae is not None:
        e["mae"] = mae
    return e

def test_classify_exit():
    assert diag._classify_exit({"exit_reason": "timeout reached"}) == "timeout"
    assert diag._classify_exit({"exit_reason": "TP hit"}) == "take_profit"
    assert diag._classify_exit({"exit_reason": "stop_loss triggered"}) == "stop_loss"
    assert diag._classify_exit({"exit_reason": "other"}) == "unknown"

def test_trade_duration_seconds():
    entry = {"entry_time": "2026-06-01T12:00:00+00:00", "exit_time": "2026-06-01T12:45:30+00:00"}
    assert round(diag._trade_duration_seconds(entry)) == 2730

def test_aggregation_and_report(tmp_path, monkeypatch, capsys):
    # Setup temporary reports/journals with sample data
    reports_root = tmp_path / "reports"
    (reports_root / "journals").mkdir(parents=True)
    j1 = [
        _make_entry("timeout", gross=-50, fees=0.5, net=-50.5,
                    entry_time="2026-06-01T10:00:00+00:00",
                    exit_time="2026-06-01T11:30:00+00:00"),
        _make_entry("TP hit", gross=120, fees=0.8, net=119.2,
                    entry_time="2026-06-02T09:00:00+00:00",
                    exit_time="2026-06-02T09:45:00+00:00",
                    mfe=0.03, mae=-0.01),
    ]
    j2 = [
        _make_entry("timeout", gross=-30, fees=0.3, net=-30.3,
                    entry_time="2026-06-03T14:15:00+00:00",
                    exit_time="2026-06-03T15:45:00+00:00"),
    ]
    (reports_root / "journals" / "run1_journal.json").write_text(json.dumps(j1))
    (reports_root / "journals" / "run2_journal.json").write_text(json.dumps(j2))
    monkeypatch.setattr(diag, "REPORTS_ROOT", reports_root)
    diag.main()
    captured = capsys.readouterr()
    assert "Diagnostic report written to" in captured.out
    report_file = next((reports_root / "diagnostics").glob("timeout_exit_report_*.json"))
    report = json.loads(report_file.read_text())
    assert report["timeout"]["trades"] == 2
    assert report["take_profit"]["trades"] == 1
    assert round(report["timeout"]["net_pnl"], 1) == -80.8
    assert round(report["take_profit"]["net_pnl"], 1) == 119.2
    assert "avg_mfe" in report["take_profit"]
    assert "avg_mae" in report["take_profit"]
    assert "avg_mfe" not in report["timeout"]

def test_no_journal_data(tmp_path, monkeypatch, capsys):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    monkeypatch.setattr(diag, "REPORTS_ROOT", empty_root)
    diag.main()
    captured = capsys.readouterr()
    assert "No journal data found" in captured.out or "No journal data found" in captured.out
    no_data_report = next((empty_root / "diagnostics").glob("timeout_exit_report_no_data_*.json"))
    report = json.loads(no_data_report.read_text())
    assert report.get("no_historical_trade_data_found") is True

def test_ignores_unrelated_json(tmp_path, monkeypatch, capsys):
    reports_root = tmp_path / "reports"
    (reports_root / "journals").mkdir(parents=True)
    (reports_root / "journals" / "config.json").write_text(json.dumps({"some": "config"}))
    monkeypatch.setattr(diag, "REPORTS_ROOT", reports_root)
    diag.main()
    captured = capsys.readouterr()
    no_data_report = next((reports_root / "diagnostics").glob("timeout_exit_report_no_data_*.json"))
    report = json.loads(no_data_report.read_text())
    assert report.get("no_historical_trade_data_found") is True
def test_ignores_diagnostic_reports_and_dedupes(tmp_path, monkeypatch, capsys):
    reports_root = tmp_path / "reports"
    (reports_root / "journals").mkdir(parents=True)
    diag_dir = reports_root / "diagnostics"
    diag_dir.mkdir(parents=True)
    
    # 1. Create a fake diagnostic report
    diag_report = {"exit_reason": "timeout", "gross_pnl": 100}
    (diag_dir / "p2_037_journal_provenance_old.json").write_text(json.dumps([diag_report]))
    
    # 2. Create duplicate trades
    trade1 = _make_entry("timeout", gross=-50, entry_time="2026-06-01T10:00:00+00:00", exit_time="2026-06-01T11:00:00+00:00")
    trade2 = _make_entry("TP hit", gross=100, entry_time="2026-06-02T10:00:00+00:00", exit_time="2026-06-02T11:00:00+00:00")
    
    (reports_root / "journals" / "run1_journal.json").write_text(json.dumps([trade1, trade2]))
    # Run2 has the exact same trade1 (duplicate)
    (reports_root / "journals" / "run2_journal.json").write_text(json.dumps([trade1]))
    
    monkeypatch.setattr(diag, "REPORTS_ROOT", reports_root)
    diag.main()
    
    report_file = next(diag_dir.glob("timeout_exit_report_*.json"))
    report = json.loads(report_file.read_text())
    
    assert report["trades_analyzed"] == 2
    assert report["timeout"]["trades"] == 1
    assert report["take_profit"]["trades"] == 1
    
    # TRADES_ANALYZED equals sum
    classified = report.get("timeout", {}).get("trades", 0) + report.get("take_profit", {}).get("trades", 0) + report.get("stop_loss", {}).get("trades", 0) + report.get("unknown", {}).get("trades", 0)
    assert report["trades_analyzed"] == classified
