"""
P2-011K — Runtime safety helpers (process lock hardening + restart-safe counters).

This module contains small, pure or near-pure helpers for:
- Robust single-process live locking (namespace aware, better stale recovery)
- Conservative reconstruction of daily counters from journal on startup/restart

All functions are safe to call from tests with mocks. No network, no writes to
broker, and (when used correctly) no writes to the production fill logger.

Intended to be called from main.py at startup only.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from utils import (
    RUNTIME_DIR,
    _acquire_process_lock_path,
    _process_lock_path_owned,
    _release_process_lock_path,
    get_runtime_namespace,
    now_utc,
)


# =============================================================================
# Process lock (hardening of existing acquire/release logic)
# =============================================================================

def acquire_live_process_lock(namespace: Optional[str] = None, force: bool = False) -> bool:
    """
    Acquire a broker-namespace-specific live lock.

    Returns True if this process now holds the lock.
    Returns False if another live process for the same namespace is running.

    This is a hardened version of the existing acquire_process_lock.
    It is namespace-aware (coinbase vs alpaca do not block each other).
    """
    ns = namespace or get_runtime_namespace()
    return _acquire_process_lock_path(RUNTIME_DIR / f"{ns}.lock", force=force)


def live_process_lock_owned(namespace: Optional[str] = None) -> bool:
    ns = namespace or get_runtime_namespace()
    return _process_lock_path_owned(RUNTIME_DIR / f"{ns}.lock")


def release_live_process_lock(namespace: Optional[str] = None) -> None:
    """Release our lock if we hold it."""
    ns = namespace or get_runtime_namespace()
    _release_process_lock_path(RUNTIME_DIR / f"{ns}.lock")


# =============================================================================
# Restart-safe daily counter reconstruction (conservative)
# =============================================================================

def reconstruct_daily_counters_from_journal(
    journal_path: Path,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Best-effort reconstruction of daily counters by scanning the journal for
    the current UTC day.

    Returns a dict with keys:
      daily_trade_count, daily_realized_pnl, consecutive_losses,
      last_trade_at, last_exit_at, _last_daily_reset_date

    This is deliberately conservative:
    - It only counts rows that look like actual placed/filled trades or exits.
    - It does not invent consecutive_losses beyond what is directly visible
      in recent EXIT rows.
    - If it cannot determine a value safely, it leaves a conservative default
      (usually 0 or the value that errs on the side of caution).
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not journal_path.exists():
        return {
            "daily_trade_count": 0,
            "daily_realized_pnl": 0.0,
            "consecutive_losses": 0,
            "last_trade_at": "",
            "last_exit_at": "",
            "_last_daily_reset_date": today,
        }

    daily_trades = 0
    daily_pnl = 0.0
    last_trade = ""
    last_exit = ""
    recent_losses = 0

    try:
        import csv
        with open(journal_path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get("timestamp", "")
                if not ts.startswith(today):
                    continue

                decision = (row.get("decision") or row.get("action") or "").upper()
                try:
                    pnl = float(row.get("pnl_usd") or row.get("gross_pnl") or 0.0)
                except Exception:
                    pnl = 0.0

                if decision in ("PLACED", "FILLED", "BUY"):
                    daily_trades += 1
                    daily_pnl += pnl
                    last_trade = ts
                elif decision == "EXIT":
                    daily_pnl += pnl
                    last_exit = ts
                    if pnl < 0:
                        recent_losses += 1
                    else:
                        recent_losses = 0
    except Exception:
        pass

    return {
        "daily_trade_count": daily_trades,
        "daily_realized_pnl": round(daily_pnl, 4),
        "consecutive_losses": recent_losses,
        "last_trade_at": last_trade,
        "last_exit_at": last_exit,
        "_last_daily_reset_date": today,
    }


def apply_reconstructed_counters(session: Any, reconstructed: Dict[str, Any]) -> None:
    """Apply reconstructed values onto a SessionState-like object (in place)."""
    for key in ("daily_trade_count", "daily_realized_pnl", "consecutive_losses",
                "last_trade_at", "last_exit_at", "_last_daily_reset_date"):
        if key in reconstructed and hasattr(session, key):
            setattr(session, key, reconstructed[key])
