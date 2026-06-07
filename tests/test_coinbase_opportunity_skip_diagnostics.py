
import json
import shutil
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coinbase_opportunity_skip_diagnostics.py"

spec = importlib.util.spec_from_file_location("diagnostics", SCRIPT)
diagnostics = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diagnostics
spec.loader.exec_module(diagnostics)

def setup_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "runtime").mkdir()
    (repo / "state" / "coinbase").mkdir(parents=True)
    # Empty heartbeat
    (repo / "runtime" / "coinbase_heartbeat.json").write_text("{}")
    # Empty open positions
    (repo / "state" / "coinbase" / "open_positions.json").write_text("{}")
    # Empty journal with header
    (repo / "journal_coinbase_crypto.csv").write_text("timestamp,symbol,action,decision,reason\n")
    return repo

def test_read_only_and_mutation_flags(tmp_path):
    repo = setup_repo(tmp_path)
    report = diagnostics.build_report(repo)
    assert report["order_mutation_performed"] is False
    assert report["state_mutation_performed"] is False
    assert report["broker_mutation_performed"] is False

def test_empty_files_produce_safe_result(tmp_path):
    repo = setup_repo(tmp_path)
    now = datetime.now(timezone.utc)
    (repo / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat()
    }))
    report = diagnostics.build_report(repo, now=now)
    assert report["recommended_next_action"] == "No journal activity found in lookback window. Check if bot is running and market data is flowing."
    assert not report["blocking_reasons"]

def test_stop_trading_classified_as_blocker(tmp_path):
    repo = setup_repo(tmp_path)
    (repo / "runtime" / "STOP_TRADING").touch()
    report = diagnostics.build_report(repo)
    assert "STOP_TRADING present" in report["blocking_reasons"]

def test_risk_halt_classified_as_blocker(tmp_path):
    repo = setup_repo(tmp_path)
    now = datetime.now(timezone.utc)
    (repo / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "risk_halt_active": True,
        "halt_reason": "test_halt",
        "last_loop_time": now.isoformat()
    }))
    report = diagnostics.build_report(repo, now=now)
    assert "Risk halt active: test_halt" in report["blocking_reasons"]

def test_journal_skips_counted_by_reason(tmp_path):
    repo = setup_repo(tmp_path)
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    (repo / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,decision,reason\n"
        f"{ts},BTC/USD,BUY,SKIP,reason_a\n"
        f"{ts},BTC/USD,BUY,SKIPPED,reason_a\n"
        f"{ts},ETH/USD,BUY,SKIP,reason_b\n"
    )
    report = diagnostics.build_report(repo, now=now)
    assert report["recent_skips_by_reason"]["reason_a"] == 2
    assert report["recent_skips_by_reason"]["reason_b"] == 1
    assert report["recent_journal_summary"]["skip_count"] == 3

def test_caps_classified_from_skips(tmp_path):
    repo = setup_repo(tmp_path)
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    (repo / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,decision,reason\n"
        f"{ts},BTC/USD,BUY,SKIP,max_open_positions reached\n"
        f"{ts},ETH/USD,BUY,SKIP,daily_trade_count limit\n"
        f"{ts},SOL/USD,BUY,SKIP,low buying_power\n"
    )
    # Also need a fresh heartbeat to avoid stale hb blocker
    (repo / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat()
    }))
    
    report = diagnostics.build_report(repo, now=now)
    assert any("Position cap reached" in r for r in report["blocking_reasons"])
    assert any("Daily trade cap reached" in r for r in report["blocking_reasons"])
    assert any("Low buying power" in r for r in report["blocking_reasons"])

def test_no_signal_returns_recommended_investigation(tmp_path):
    repo = setup_repo(tmp_path)
    now = datetime.now(timezone.utc)
    (repo / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat()
    }))
    # Journal has some activity but no PLACED/SKIP (e.g. just evaluation logs)
    # Actually my script counts SKIPS. If there are NO skips and NO buys/sells:
    (repo / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,decision,reason\n"
        f"{now.isoformat()},BTC/USD,BUY,EVAL,no signal\n"
    )
    report = diagnostics.build_report(repo, now=now)
    assert "No clear blockers found" in report["recommended_next_action"]

def test_json_schema_fields(tmp_path):
    repo = setup_repo(tmp_path)
    report = diagnostics.build_report(repo)
    required = [
        "report_class", "schema_version", "generated_at_utc", "git_head",
        "mode_detected", "stop_trading_present", "heartbeat", "runtime_health",
        "risk_config_detected", "account_snapshot_from_heartbeat",
        "local_open_positions", "recent_journal_summary", "recent_trade_decisions",
        "recent_skips_by_reason", "symbols_evaluated", "candidate_opportunities",
        "blocking_reasons", "profitability_relevance", "recommended_next_action",
        "order_mutation_performed", "state_mutation_performed", "broker_mutation_performed"
    ]
    for field in required:
        assert field in report

def test_no_broker_imports():
    with open(SCRIPT, "r") as f:
        content = f.read()
    assert "broker_coinbase" not in content
    assert "create_order" not in content
    assert "cancel_order" not in content
    assert "place_order" not in content
    assert "close_position" not in content
