import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.governance_bootstrap as bootstrap

def test_base_has_required_file(monkeypatch, tmp_path):
    def mock_run(*args, **kwargs):
        class Res:
            returncode = 0
            stdout = "mock"
        return Res()
    monkeypatch.setattr(bootstrap.subprocess, "run", mock_run)
    
    # Mock file_exists_on_ref to return True for base
    monkeypatch.setattr(bootstrap, "file_exists_on_ref", lambda ref, file, dry: True)
    
    transcript_path = tmp_path / "t.txt"
    monkeypatch.setattr(sys, "argv", [
        "gov.py", "start", "--patch", "P2", "--branch", "rev", 
        "--requires-file", "file.py", "--dependency-branch", "dep", 
        "--dependency-commit", "commit1", "--base", "main", "--transcript", str(transcript_path)
    ])
    
    # Mock pbcopy
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: type("M", (), {"communicate": lambda self, x: None})())
    
    bootstrap.main()
    content = transcript_path.read_text()
    assert "NEXT_ACTION=created_from_base" in content
    
def test_base_missing_dep_has_file(monkeypatch, tmp_path):
    def mock_run(*args, **kwargs):
        class Res:
            returncode = 0
            stdout = "commit1"
        return Res()
    monkeypatch.setattr(bootstrap.subprocess, "run", mock_run)
    
    def mock_file_exists(ref, file, dry):
        return ref.startswith("origin/dep")
    monkeypatch.setattr(bootstrap, "file_exists_on_ref", mock_file_exists)
    monkeypatch.setattr(bootstrap, "remote_branch_exists", lambda b: True)
    
    transcript_path = tmp_path / "t.txt"
    monkeypatch.setattr(sys, "argv", [
        "gov.py", "start", "--patch", "P2", "--branch", "rev", 
        "--requires-file", "file.py", "--dependency-branch", "dep", 
        "--dependency-commit", "commit1", "--base", "main", "--transcript", str(transcript_path)
    ])
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: type("M", (), {"communicate": lambda self, x: None})())
    
    bootstrap.main()
    content = transcript_path.read_text()
    assert "NEXT_ACTION=created_from_dependency_branch" in content
    assert "MERGE ORDER REQUIRED:" in content

def test_dependency_commit_mismatch(monkeypatch, tmp_path):
    def mock_run(*args, **kwargs):
        class Res:
            returncode = 0
            stdout = "wrongcommit"
        return Res()
    monkeypatch.setattr(bootstrap.subprocess, "run", mock_run)
    
    monkeypatch.setattr(bootstrap, "file_exists_on_ref", lambda ref, file, dry: False)
    monkeypatch.setattr(bootstrap, "remote_branch_exists", lambda b: True)
    
    transcript_path = tmp_path / "t.txt"
    monkeypatch.setattr(sys, "argv", [
        "gov.py", "start", "--patch", "P2", "--branch", "rev", 
        "--requires-file", "file.py", "--dependency-branch", "dep", 
        "--dependency-commit", "commit1", "--base", "main", "--transcript", str(transcript_path)
    ])
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: type("M", (), {"communicate": lambda self, x: None})())
    
    with pytest.raises(SystemExit) as e:
        bootstrap.main()
    assert e.value.code == 1
    content = transcript_path.read_text()
    assert "ABORT: remote dependency branch HEAD (wrongcommit) does not match expected commit (commit1)" in content

def test_missing_everywhere(monkeypatch, tmp_path):
    def mock_run(*args, **kwargs):
        class Res:
            returncode = 0
            stdout = "commit1"
        return Res()
    monkeypatch.setattr(bootstrap.subprocess, "run", mock_run)
    
    monkeypatch.setattr(bootstrap, "file_exists_on_ref", lambda ref, file, dry: False)
    monkeypatch.setattr(bootstrap, "remote_branch_exists", lambda b: True)
    
    transcript_path = tmp_path / "t.txt"
    monkeypatch.setattr(sys, "argv", [
        "gov.py", "start", "--patch", "P2", "--branch", "rev", 
        "--requires-file", "file.py", "--dependency-branch", "dep", 
        "--dependency-commit", "commit1", "--base", "main", "--transcript", str(transcript_path)
    ])
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: type("M", (), {"communicate": lambda self, x: None})())
    
    with pytest.raises(SystemExit) as e:
        bootstrap.main()
    assert e.value.code == 1
    content = transcript_path.read_text()
    assert "ABORT: required file missing from base and dependency branch" in content

def test_dry_run(monkeypatch, tmp_path, capsys):
    def mock_run(*args, **kwargs):
        class Res:
            returncode = 0
            stdout = "commit1"
        return Res()
    monkeypatch.setattr(bootstrap.subprocess, "run", mock_run)
    
    monkeypatch.setattr(bootstrap, "file_exists_on_ref", lambda ref, file, dry: True)
    
    transcript_path = tmp_path / "t.txt"
    monkeypatch.setattr(sys, "argv", [
        "gov.py", "start", "--patch", "P2", "--branch", "rev", 
        "--requires-file", "file.py", "--dependency-branch", "dep", 
        "--dependency-commit", "commit1", "--base", "main", "--transcript", str(transcript_path), "--dry-run"
    ])
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: type("M", (), {"communicate": lambda self, x: None})())
    
    bootstrap.main()
    captured = capsys.readouterr().out
    assert "[DRY-RUN] Create branch from base: git checkout -b rev main" in captured
