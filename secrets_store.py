#!/usr/bin/env python3
"""
secrets_store.py — P2-046P: macOS Keychain-backed credential store (for in-app key entry).

Lets the app save Alpaca keys to the encrypted macOS Keychain (via the native `security` tool),
so a user never edits `.env`. Credential resolution order is env var → Keychain → `.env`, so dev
overrides and existing `.env` setups keep working.

GOVERNANCE: secrets only. Values are never printed/logged/committed. The `runner` is injected so
this is fully unit-tested without touching the real Keychain.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

SERVICE = "Accumulator"  # Keychain service name
Runner = Callable[..., SimpleNamespace]


def set_secret(name: str, value: str, *, runner: Runner = subprocess.run) -> bool:
    """Store/replace a secret in the Keychain. Returns True on success."""
    if not value:
        return False
    try:
        runner(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", name, "-w", value],
               check=True, capture_output=True)
        return True
    except Exception:
        return False


def get_secret(name: str, *, runner: Runner = subprocess.run) -> Optional[str]:
    """Read a secret from the Keychain, or None if absent / unavailable."""
    try:
        r = runner(["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"],
                   check=True, capture_output=True, text=True)
        out = (r.stdout or "").strip()
        return out or None
    except Exception:
        return None


def delete_secret(name: str, *, runner: Runner = subprocess.run) -> bool:
    try:
        runner(["security", "delete-generic-password", "-s", SERVICE, "-a", name],
               check=True, capture_output=True)
        return True
    except Exception:
        return False


def has_secret(name: str, *, runner: Runner = subprocess.run) -> bool:
    return get_secret(name, runner=runner) is not None


def get_credential(name: str, *, runner: Runner = subprocess.run, env_path: str = ".env") -> Optional[str]:
    """Resolve a credential: environment variable → Keychain → .env file."""
    v = os.getenv(name)
    if v:
        return v
    v = get_secret(name, runner=runner)
    if v:
        return v
    p = Path(env_path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, val = line.split("=", 1)
            if k.strip() == name:
                return val.strip().strip('"').strip("'") or None
    return None
