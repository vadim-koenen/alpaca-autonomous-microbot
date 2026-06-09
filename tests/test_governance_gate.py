import pytest
import sys
from pathlib import Path

# Setup paths
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.governance_gate as gate

def test_command_construction_uses_shell_false():
    # Inspection test: check that run_cmd defaults to shell=False
    import inspect
    sig = inspect.signature(gate.run_cmd)
    assert sig.parameters["shell"].default is False

def test_forbidden_path_detection():
    # Test our manual check logic without real git
    def mock_run_cmd(cmd, **kwargs):
        if cmd == ["git", "ls-files"]:
            return "runtime/coinbase.lock\nscripts/main.py\nstate/db.sqlite\n.env\nlogs/app.log\np2_035a_transcript.txt"
        return ""
        
    original_run_cmd = gate.run_cmd
    gate.run_cmd = mock_run_cmd
    try:
        with pytest.raises(SystemExit):
            gate.check_forbidden_tracked_files()
    finally:
        gate.run_cmd = original_run_cmd

def test_patch_only_static_scan_contextual(monkeypatch):
    def mock_run_cmd(cmd, **kwargs):
        if cmd == ["git", "diff", "-U0"]:
            return "+++ b/tests/test_something.py\n+ def test_mock(): launchctl cancel_order close_position\n+++ b/scripts/main.py\n+ def oops(): launchctl"
        return ""
    
    monkeypatch.setattr(gate, "run_cmd", mock_run_cmd)
    hits = gate.patch_static_scan()
    assert len(hits["allowed_contextual_hits"]) == 3 # launchctl, cancel_order, close_position
    assert len(hits["disallowed_hits"]) == 1 # main.py oops launchctl
    assert "main.py: launchctl" in hits["disallowed_hits"][0]

def test_verify_review_transcript_declarations(monkeypatch, tmp_path):
    # Mock all commands
    def mock_run_cmd(cmd, **kwargs):
        if cmd == ["git", "branch", "--show-current"]:
            return "review/p2-035a-operational-net-alerts"
        elif cmd == ["git", "branch", "--contains", "origin/main"]:
            return "* review/p2-035a-operational-net-alerts\n  origin/main"
        elif cmd == ["git", "rev-parse", "HEAD"]:
            return "abcdef123"
        elif cmd == ["git", "ls-remote", "origin", "review/p2-035a-operational-net-alerts"]:
            return "abcdef123\trefs/heads/review/p2-035a-operational-net-alerts"
        elif cmd == ["git", "ls-files"]:
            return "scripts/main.py"
        elif cmd == ["git", "diff", "-U0"]:
            return "+++ b/scripts/main.py\n+ print('hello')"
        return "mock"
        
    monkeypatch.setattr(gate, "run_cmd", mock_run_cmd)
    
    import subprocess
    def mock_subprocess_run(*args, **kwargs):
        class Res:
            returncode = 0
            stdout = "mock out"
            stderr = ""
        return Res()
    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: type("MockPopen", (), {"communicate": lambda self, *a: None})())
    
    # We will simulate calling main with args
    test_transcript = tmp_path / "transcript.txt"
    monkeypatch.setattr(sys, "argv", [
        "governance_gate.py", 
        "verify-review", 
        "--branch", "review/p2-035a-operational-net-alerts", 
        "--base", "origin/main", 
        "--smoke", "echo smoke", 
        "--transcript", str(test_transcript)
    ])
    
    try:
        gate.main()
    except SystemExit as e:
        assert e.code == 0
        
    content = test_transcript.read_text(encoding="utf-8")
    assert "REVIEW_BRANCH_PUSHED=true" in content
    assert "MAIN_PUSHED=false" in content
    assert "SECRETS_READ_OR_PRINTED=false" in content
