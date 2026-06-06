import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import utils


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_lock_handles():
    yield
    for key, handle in list(utils._PROCESS_LOCK_HANDLES.items()):
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        except OSError:
            pass
        utils._PROCESS_LOCK_HANDLES.pop(key, None)


def configure_live_lock(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(utils, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(utils, "get_mode", lambda: "live")
    monkeypatch.setattr(utils, "get_runtime_namespace", lambda: "coinbase")


def test_successful_single_owner_and_runtime_ownership_check(tmp_path, monkeypatch):
    configure_live_lock(monkeypatch, tmp_path)
    assert utils.acquire_process_lock() is True
    assert utils.process_lock_owned() is True
    assert (tmp_path / "coinbase.lock").read_text(encoding="utf-8") == str(os.getpid())
    utils.release_process_lock()
    assert not (tmp_path / "coinbase.lock").exists()


def test_alive_atomic_lock_owner_refuses_acquisition_even_with_force(tmp_path, monkeypatch):
    configure_live_lock(monkeypatch, tmp_path)
    lock_path = tmp_path / "coinbase.lock"
    guard_path = tmp_path / ".coinbase.lock.guard"
    ready = tmp_path / "ready"
    code = (
        "import fcntl,os,sys,time,pathlib;"
        "p=pathlib.Path(sys.argv[1]);g=pathlib.Path(sys.argv[2]);r=pathlib.Path(sys.argv[3]);"
        "p.parent.mkdir(parents=True,exist_ok=True);"
        "h=g.open('a+');fcntl.flock(h.fileno(),fcntl.LOCK_EX);"
        "p.write_text(str(os.getpid()));"
        "r.write_text('ready');time.sleep(10)"
    )
    owner = subprocess.Popen([
        sys.executable,
        "-c",
        code,
        str(lock_path),
        str(guard_path),
        str(ready),
    ])
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.02)
        assert ready.exists()
        assert utils.acquire_process_lock() is False
        assert utils.acquire_process_lock(force=True) is False
    finally:
        owner.terminate()
        owner.wait(timeout=5)


def test_stale_lock_metadata_can_be_replaced_safely(tmp_path, monkeypatch):
    configure_live_lock(monkeypatch, tmp_path)
    lock_path = tmp_path / "coinbase.lock"
    lock_path.write_text("99999999", encoding="utf-8")
    assert utils.acquire_process_lock() is True
    assert utils.process_lock_owned() is True
    assert lock_path.read_text(encoding="utf-8") == str(os.getpid())


def test_runtime_ownership_check_fails_if_lock_path_is_replaced(tmp_path, monkeypatch):
    configure_live_lock(monkeypatch, tmp_path)
    lock_path = tmp_path / "coinbase.lock"
    assert utils.acquire_process_lock() is True
    lock_path.unlink()
    lock_path.write_text("77777777", encoding="utf-8")
    assert utils.process_lock_owned() is False
    utils.release_process_lock()
    assert lock_path.exists()


def test_non_live_mode_preserves_existing_no_lock_behavior(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(utils, "get_mode", lambda: "paper")
    assert utils.acquire_process_lock() is True
    assert utils.process_lock_owned() is True
    assert not (tmp_path / "coinbase.lock").exists()


def test_main_rechecks_lock_before_live_cycle_and_emits_alert():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "if mode == \"live\" and not process_lock_owned()" in text
    assert "process_lock_ownership_lost" in text
    assert "Duplicate live process startup refused" in text
