"""
P2-011K tests for the hardened live process lock (namespace-aware).

These tests use temp directories and do not touch the real runtime/ or any live lock files.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime_safety import acquire_live_process_lock, release_live_process_lock


def test_lock_acquire_and_release_same_namespace(tmp_path, monkeypatch):
    """Basic acquire/release cycle for one namespace."""
    monkeypatch.setattr("runtime_safety.RUNTIME_DIR", tmp_path)
    monkeypatch.setattr("utils.RUNTIME_DIR", tmp_path)  # for any shared constants

    with patch("runtime_safety.get_runtime_namespace", return_value="coinbase"):
        assert acquire_live_process_lock() is True
        assert (tmp_path / "coinbase.lock").exists()
        release_live_process_lock()
        assert not (tmp_path / "coinbase.lock").exists()


def test_second_process_same_namespace_is_blocked(tmp_path, monkeypatch):
    """Second acquire for same namespace while first holds it should fail."""
    monkeypatch.setattr("runtime_safety.RUNTIME_DIR", tmp_path)

    with patch("runtime_safety.get_runtime_namespace", return_value="coinbase"):
        assert acquire_live_process_lock() is True
        # Simulate second process
        assert acquire_live_process_lock() is False
        release_live_process_lock()


def test_different_namespace_does_not_block(tmp_path, monkeypatch):
    """Alpaca and Coinbase namespaces are independent."""
    monkeypatch.setattr("runtime_safety.RUNTIME_DIR", tmp_path)

    with patch("runtime_safety.get_runtime_namespace", return_value="coinbase"):
        assert acquire_live_process_lock() is True

    with patch("runtime_safety.get_runtime_namespace", return_value="alpaca"):
        assert acquire_live_process_lock() is True  # different namespace

    # Cleanup
    with patch("runtime_safety.get_runtime_namespace", return_value="coinbase"):
        release_live_process_lock()
    with patch("runtime_safety.get_runtime_namespace", return_value="alpaca"):
        release_live_process_lock()


def test_stale_lock_is_recoverable(tmp_path, monkeypatch):
    """If lock file exists with dead PID, we can acquire."""
    monkeypatch.setattr("runtime_safety.RUNTIME_DIR", tmp_path)

    lock = tmp_path / "coinbase.lock"
    # Write a PID that is extremely unlikely to exist
    lock.write_text("999999999")

    with patch("runtime_safety.get_runtime_namespace", return_value="coinbase"):
        # Should succeed because PID is dead
        assert acquire_live_process_lock() is True
        release_live_process_lock()
