#!/usr/bin/env python3
"""
P2-011K — Read-only Coinbase ops status / health probe.

This script is safe to run at any time. It reads local state, journal, reports,
and runtime artifacts to give an operator a quick view of the bot's situation
without making broker calls or causing any side effects.

It is intended for use by humans and monitoring scripts.

Example:
    python3 scripts/coinbase_ops_status.py
    python3 scripts/coinbase_ops_status.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Make runnable from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import RUNTIME_DIR, get_runtime_namespace

try:
    from position_manager import PositionManager  # only for type hints / optional
except Exception:
    PositionManager = None  # type: ignore


def _read_json_safe(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _tail_journal_lines(journal_path: Path, n: int = 20) -> List[str]:
    if not journal_path.exists():
        return []
    try:
        result = subprocess.run(
            ["tail", "-n", str(n), str(journal_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip().splitlines()[-n:]
    except Exception:
        return []


def get_process_count_for_namespace(namespace: str) -> int:
    """
    Best-effort count of live bot processes for the namespace.

    Strategy (macOS/launchd friendly):
    1. Trust the runtime/<ns>.lock file if its PID is alive (most reliable after P2-011K hardening).
    2. Fall back to pgrep heuristic.
    3. Fall back to launchctl list for the known launchd label.
    """
    count = 0
    lock_file = RUNTIME_DIR / f"{namespace}.lock"

    # 1. Lock file (preferred signal after P2-011K)
    if lock_file.exists():
        try:
            pid = int(lock_file.read_text().strip())
            os.kill(pid, 0)
            count = max(count, 1)
        except (ProcessLookupError, ValueError, PermissionError, OSError):
            pass

    # 2. pgrep heuristic
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"python.*alpaca-autonomous-microbot.*{namespace}"],
            capture_output=True, text=True, timeout=3
        )
        pids = [p for p in result.stdout.strip().splitlines() if p.strip()]
        if pids:
            count = max(count, len(pids))
    except Exception:
        pass

    # 3. launchctl (for launchd-managed bots)
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=3
        )
        labels = result.stdout.lower()
        if f"com.vadim.{namespace}-crypto-bot" in labels or f"com.vadim.{namespace}-bot" in labels:
            count = max(count, 1)
    except Exception:
        pass

    return count


def build_status() -> Dict[str, Any]:
    try:
        namespace = get_runtime_namespace()
    except RuntimeError:
        # This script is Coinbase-specific and must be safe to run from an
        # empty shell/test environment. Runtime startup can remain strict;
        # ops status defaults to Coinbase for read-only diagnostics.
        namespace = "coinbase"
    lock_file = RUNTIME_DIR / f"{namespace}.lock"
    heartbeat_file = RUNTIME_DIR / f"{namespace}_heartbeat.json"
    open_positions_file = Path("state") / namespace / "open_positions.json"
    journal_file = Path(f"journal_{namespace}.csv") if namespace else Path("journal.csv")

    # Try common report locations
    reports_dir = Path("reports")
    latest_report = None
    if reports_dir.exists():
        reports = sorted(reports_dir.glob("*.txt")) + sorted(reports_dir.glob("*.md"))
        if reports:
            latest_report = str(reports[-1])

    lock_info: Dict[str, Any] = {}
    if lock_file.exists():
        try:
            pid = int(lock_file.read_text().strip())
            lock_info = {"pid": pid, "alive": False}
            try:
                os.kill(pid, 0)
                lock_info["alive"] = True
            except ProcessLookupError:
                lock_info["alive"] = False
        except Exception:
            lock_info = {"raw": lock_file.read_text().strip()[:200]}

    heartbeat = _read_json_safe(heartbeat_file)
    raw_state = _read_json_safe(open_positions_file)

    # The real structure after P2-011x is:
    # { "saved_at": ..., "state_namespace": ..., "positions": { "BTC/USD": {...}, ... } }
    positions = raw_state.get("positions", raw_state) if isinstance(raw_state, dict) else {}

    # Count only actual position entries
    open_positions_count = len(positions) if isinstance(positions, dict) else 0

    # Local exposure: prefer "notional", fallback to abs(qty * entry_price)
    local_exposure = 0.0
    if isinstance(positions, dict):
        for pos in positions.values():
            if not isinstance(pos, dict):
                continue
            notional = pos.get("notional")
            if notional is not None:
                try:
                    local_exposure += float(notional)
                    continue
                except Exception:
                    pass
            # Fallback
            try:
                qty = float(pos.get("qty", 0) or 0)
                entry_price = float(pos.get("entry_price", 0) or 0)
                local_exposure += abs(qty * entry_price)
            except Exception:
                pass

    process_count = get_process_count_for_namespace(namespace)

    recent_journal = _tail_journal_lines(journal_file, 8)

    status = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "namespace": namespace,
        "lock": lock_info,
        "detected_live_processes": process_count,
        "heartbeat": heartbeat,
        "open_positions_file": str(open_positions_file),
        "open_positions_count": open_positions_count,
        "local_tracked_exposure_usd": round(local_exposure, 4),
        "latest_report": latest_report,
        "journal_tail": recent_journal,
        "warnings": [],
    }

    if process_count > 1:
        status["warnings"].append(
            f"Multiple live processes detected for namespace {namespace} ({process_count}). "
            "This can cause duplicate trades and broken counters."
        )
    if lock_info.get("alive") is False and lock_info:
        status["warnings"].append(
            "Lock file exists but PID is dead — will be auto-recovered on next startup."
        )

    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Coinbase ops status probe (P2-011K)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    status = build_status()

    if args.json:
        print(json.dumps(status, indent=2, default=str))
        return

    print("=== Coinbase Ops Status (read-only) ===")
    print(f"Namespace      : {status['namespace']}")
    print(f"Generated (UTC): {status['generated_at_utc']}")
    print(f"Lock file      : {status['lock']}")
    print(f"Live processes : {status['detected_live_processes']}")
    print(f"Open positions : {status['open_positions_count']}")
    print(f"Local exposure : ${status['local_tracked_exposure_usd']}")
    if status['latest_report']:
        print(f"Latest report  : {status['latest_report']}")
    if status['warnings']:
        print("\nWarnings:")
        for w in status['warnings']:
            print(f"  - {w}")
    print("\nRecent journal (tail):")
    for line in status['journal_tail'][-5:]:
        print(f"  {line}")
    print("\n(For full details use --json)")


if __name__ == "__main__":
    main()
