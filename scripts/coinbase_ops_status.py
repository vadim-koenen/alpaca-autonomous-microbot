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
    """Best-effort count of processes that look like the bot for this namespace."""
    try:
        # Look for python processes mentioning the bot script and the namespace
        # This is heuristic and read-only.
        result = subprocess.run(
            ["pgrep", "-f", f"python.*alpaca-autonomous-microbot.*{namespace}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        pids = [p for p in result.stdout.strip().splitlines() if p.strip()]
        return len(pids)
    except Exception:
        return -1  # unknown


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
    open_positions = _read_json_safe(open_positions_file)

    # Rough local exposure from state
    local_exposure = 0.0
    for pos in open_positions.values():
        try:
            local_exposure += float(pos.get("notional", 0) or 0)
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
        "open_positions_count": len(open_positions),
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
