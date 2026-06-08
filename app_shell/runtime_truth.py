from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_from_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _age_seconds(mtime: float | None, now: datetime) -> float | None:
    if mtime is None:
        return None
    return max(0.0, (now - datetime.fromtimestamp(mtime, tz=timezone.utc)).total_seconds())


def _file_info(repo_root: Path, relative: str, kind: str, now: datetime, json_file: bool = False) -> dict[str, Any]:
    path = repo_root / relative
    if not path.exists():
        return {
            "present": False,
            "kind": kind,
            "mtime": None,
            "size_bytes": None,
            "age_seconds": None,
            "valid_json": None if json_file else None,
            "keys": [] if json_file else None,
        }

    stat = path.stat()
    info: dict[str, Any] = {
        "present": True,
        "kind": kind,
        "mtime": _iso_from_timestamp(stat.st_mtime),
        "size_bytes": stat.st_size,
        "age_seconds": _age_seconds(stat.st_mtime, now),
    }

    if json_file:
        info["valid_json"] = False
        info["keys"] = []
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            info["valid_json"] = True
            if isinstance(parsed, dict):
                info["keys"] = sorted(str(k) for k in parsed.keys())
            elif isinstance(parsed, list):
                info["keys"] = ["list"]
            else:
                info["keys"] = [type(parsed).__name__]
        except Exception:
            info["valid_json"] = False
            info["keys"] = []

    return info


def _detect_live_process() -> dict[str, Any]:
    query = " ".join(["main.py", "--mode", "live"])
    try:
        result = subprocess.run(
            ["pgrep", "-af", query],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return {
            "detected": False,
            "matches": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    matches = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and "pgrep" not in line
    ]

    return {
        "detected": bool(matches),
        "matches": matches,
        "error": None,
    }


def build_runtime_truth(repo_root: Path) -> dict[str, Any]:
    repo_root = Path(repo_root)
    now = _utc_now()
    live = _detect_live_process()

    files = {
        "runtime/STOP_TRADING": _file_info(
            repo_root,
            "runtime/STOP_TRADING",
            "guard_file",
            now,
            json_file=False,
        ),
        "runtime/heartbeat.json": _file_info(
            repo_root,
            "runtime/heartbeat.json",
            "json_runtime_file",
            now,
            json_file=True,
        ),
        "runtime/coinbase_heartbeat.json": _file_info(
            repo_root,
            "runtime/coinbase_heartbeat.json",
            "json_runtime_file",
            now,
            json_file=True,
        ),
    }

    stop_present = bool(files["runtime/STOP_TRADING"]["present"])
    live_detected = bool(live["detected"])

    return {
        "schema": "runtime_truth.v1",
        "generated_at": now.isoformat(),
        "read_only": True,
        "broker_calls_made": False,
        "order_mutation_performed": False,
        "state_mutation_performed": False,
        "guards": {
            "stop_trading_present": stop_present,
            "live_process_detected": live_detected,
        },
        "runtime_files": files,
        "processes": {
            "live_process": live,
        },
        "summary": {
            "stop_trading": "present" if stop_present else "absent",
            "live_process": "detected" if live_detected else "not_detected",
            "mode": "read_only",
        },
    }
