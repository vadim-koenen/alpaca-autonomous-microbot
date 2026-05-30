# ADVISORY ONLY — tooling automation only, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Unit tests for handoff_daemon.py — P2-001I
"""

import json
import os
import shutil
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from handoff_daemon import run_cycle, MARKER_FILE, LOG_FILE, COMPLETED_DIR

@pytest.fixture
def clean_env(tmp_path):
    # Setup a mock repo root
    mock_root = tmp_path / "repo"
    mock_root.mkdir()
    docs_dir = mock_root / "docs"
    docs_dir.mkdir()
    logs_dir = mock_root / "logs"
    logs_dir.mkdir()
    scripts_dir = mock_root / "scripts"
    scripts_dir.mkdir()
    
    marker_file = docs_dir / "PENDING_PATCH_COMPLETION.json"
    log_file = logs_dir / "handoff_daemon.log"
    completed_dir = docs_dir / "completed_patch_requests"
    
    with patch("handoff_daemon.REPO_ROOT", mock_root), \
         patch("handoff_daemon.MARKER_FILE", marker_file), \
         patch("handoff_daemon.LOG_FILE", log_file), \
         patch("handoff_daemon.COMPLETED_DIR", completed_dir), \
         patch("handoff_daemon.COMPLETE_PATCH_SCRIPT", scripts_dir / "complete_patch.py"):
        yield {
            "root": mock_root,
            "marker": marker_file,
            "log": log_file,
            "completed": completed_dir
        }

def test_missing_marker(clean_env):
    assert run_cycle() == 0
    assert not clean_env["log"].exists()

def test_malformed_json(clean_env):
    clean_env["marker"].write_text("not json")
    assert run_cycle() == 1
    assert "Malformed JSON" in clean_env["log"].read_text()
    assert clean_env["marker"].exists()

def test_missing_required_field(clean_env):
    clean_env["marker"].write_text(json.dumps({"patch": "P1"}))
    assert run_cycle() == 1
    assert "Missing required fields" in clean_env["log"].read_text()
    assert clean_env["marker"].exists()

@patch("subprocess.run")
def test_invalid_patch_commit(mock_run, clean_env):
    data = {
        "patch": "P2-001X",
        "title": "Title",
        "patch_commit": "invalid",
        "summary": "Sum",
        "next": "Next",
        "created_at": "2026-05-30T10:00:00Z",
        "created_by": "user"
    }
    clean_env["marker"].write_text(json.dumps(data))
    
    # Mock git cat-file failure
    mock_run.return_value = MagicMock(returncode=1)
    
    assert run_cycle() == 1
    assert "Commit invalid not found in git" in clean_env["log"].read_text()
    assert clean_env["marker"].exists()

@patch("subprocess.run")
def test_dirty_git_state(mock_run, clean_env):
    data = {
        "patch": "P2-001X",
        "title": "Title",
        "patch_commit": "abc1234",
        "summary": "Sum",
        "next": "Next",
        "created_at": "2026-05-30T10:00:00Z",
        "created_by": "user"
    }
    clean_env["marker"].write_text(json.dumps(data))
    
    # Mock git cat-file success (0), then git status dirty (1)
    mock_run.side_effect = [
        MagicMock(returncode=0), # cat-file
        MagicMock(returncode=0, stdout="M  main.py\n") # git status (M + space + space + path)
    ]
    
    assert run_cycle() == 1
    assert "Unexpected dirty tracked file: main.py" in clean_env["log"].read_text()
    assert clean_env["marker"].exists()

@patch("subprocess.run")
def test_complete_patch_failure(mock_run, clean_env):
    data = {
        "patch": "P2-001X",
        "title": "Title",
        "patch_commit": "abc1234",
        "summary": "Sum",
        "next": "Next",
        "created_at": "2026-05-30T10:00:00Z",
        "created_by": "user"
    }
    clean_env["marker"].write_text(json.dumps(data))
    
    # Mock success for cat-file and git status, then failure for complete_patch.py
    mock_run.side_effect = [
        MagicMock(returncode=0), # cat-file
        MagicMock(returncode=0, stdout=""), # git status
        MagicMock(returncode=1, stdout="error", stderr="err") # complete_patch.py
    ]
    
    assert run_cycle() == 1
    assert "complete_patch.py failed" in clean_env["log"].read_text()
    assert clean_env["marker"].exists()

@patch("subprocess.run")
def test_successful_run(mock_run, clean_env):
    data = {
        "patch": "P2-001X",
        "title": "Title",
        "patch_commit": "abc1234",
        "summary": "Sum",
        "next": "Next",
        "created_at": "2026-05-30T10:00:00Z",
        "created_by": "user"
    }
    clean_env["marker"].write_text(json.dumps(data))
    
    mock_run.side_effect = [
        MagicMock(returncode=0), # cat-file
        MagicMock(returncode=0, stdout=""), # git status
        MagicMock(returncode=0) # complete_patch.py
    ]
    
    assert run_cycle() == 0
    assert "SUCCESS" in clean_env["log"].read_text()
    assert not clean_env["marker"].exists()
    assert len(list(clean_env["completed"].glob("*.json"))) == 1

@patch("subprocess.run")
def test_dry_run(mock_run, clean_env):
    data = {
        "patch": "P2-001X",
        "title": "Title",
        "patch_commit": "abc1234",
        "summary": "Sum",
        "next": "Next",
        "created_at": "2026-05-30T10:00:00Z",
        "created_by": "user"
    }
    clean_env["marker"].write_text(json.dumps(data))
    
    mock_run.side_effect = [
        MagicMock(returncode=0), # cat-file
        MagicMock(returncode=0, stdout="") # git status
    ]
    
    assert run_cycle(dry_run=True) == 0
    assert "DRYRUN" in clean_env["log"].read_text()
    assert clean_env["marker"].exists()
    # Ensure complete_patch.py was NOT called
    assert mock_run.call_count == 2
