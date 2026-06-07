
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
import unittest.mock as mock
import pytest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from app_shell.server import DashboardAPI

def setup_api(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "runtime").mkdir()
    (repo / "reports").mkdir()
    return DashboardAPI(repo), repo

def test_api_status_returns_correct_data(tmp_path):
    api, repo = setup_api(tmp_path)
    (repo / "runtime" / "STOP_TRADING").touch()
    
    data = api.get_status()
        
    assert data["stop_trading_present"] is True
    assert data["read_only"] is True
    assert "git_head" in data

def test_api_heartbeat_returns_safe_json_if_missing(tmp_path):
    api, repo = setup_api(tmp_path)
    data = api.get_coinbase_heartbeat()
    assert data == {}

def test_api_heartbeat_returns_data_if_present(tmp_path):
    api, repo = setup_api(tmp_path)
    hb_data = {"status": "running", "equity": 100.0}
    (repo / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps(hb_data))
    
    data = api.get_coinbase_heartbeat()
        
    assert data["status"] == "running"
    assert data["equity"] == 100.0

def test_api_diagnostics_latest_finds_correct_file(tmp_path):
    api, repo = setup_api(tmp_path)
    diag_dir = repo / "reports" / "coinbase_diagnostics"
    diag_dir.mkdir(parents=True)
    
    f1 = diag_dir / "coinbase_opportunity_skip_diagnostics_OLD.json"
    f1.write_text(json.dumps({"id": "old"}))
    os.utime(f1, (1000, 1000))
    
    f2 = diag_dir / "coinbase_opportunity_skip_diagnostics_NEW.json"
    f2.write_text(json.dumps({"id": "new"}))
    os.utime(f2, (2000, 2000))
    
    data = api.get_latest_diagnostics()
        
    assert data["id"] == "new"

def test_no_mutation_endpoints_exist():
    # server.py ReadOnlyDashboardHandler handle_api logic check
    server_path = ROOT / "app_shell" / "server.py"
    content = server_path.read_text()
    
    assert "def do_POST" not in content
    assert "def do_PUT" not in content
    assert "def do_DELETE" not in content

def test_server_does_not_import_broker_modules():
    # Read server.py content
    server_path = ROOT / "app_shell" / "server.py"
    content = server_path.read_text()
    
    forbidden = ["broker_coinbase", "broker_alpaca", "create_order", "place_order", "cancel_order"]
    for f in forbidden:
        assert f not in content

def test_frontend_update_targets_exist_in_html():
    import re
    html = (ROOT / "app_shell" / "static" / "index.html").read_text()
    js = (ROOT / "app_shell" / "static" / "app.js").read_text()

    html_ids = set(re.findall(r'id="([^"]+)"', html))
    js_update_refs = set(re.findall(r"updateElement\(['\"]([^'\"]+)", js))

    missing = sorted(js_update_refs - html_ids)
    assert missing == []

