#!/usr/bin/env python3
"""
Offline Coinbase trading LaunchAgent/process audit.

This inspects local plist files only. It does not call brokers, read .env,
invoke launchctl, restart/kill processes, or mutate system state.
"""

from __future__ import annotations

import argparse
import json
import plistlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAUNCHAGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _flatten_plist_text(data: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("Label", "WorkingDirectory", "Program", "StandardOutPath", "StandardErrorPath"):
        if data.get(key):
            parts.append(str(data.get(key)))
    parts.extend(_as_list(data.get("ProgramArguments")))
    env = data.get("EnvironmentVariables")
    if isinstance(env, dict):
        for key, value in env.items():
            parts.append(str(key))
            parts.append(str(value))
    return " ".join(parts).lower()


def classify_plist(path: Path) -> Dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = plistlib.load(handle)
    except Exception as exc:
        return {
            "plist_path": str(path),
            "label": None,
            "program_arguments": [],
            "classification": "unknown",
            "confidence": "low",
            "recommended_restart_target": None,
            "reason": f"plist_parse_error:{exc}",
        }

    if not isinstance(data, dict):
        data = {}
    label = str(data.get("Label", ""))
    args = _as_list(data.get("ProgramArguments"))
    text = _flatten_plist_text(data)

    is_price_logger = (
        "price-path-logger" in text
        or "price_path_logger" in text
        or "coinbase_price_path_logger.py" in text
    )
    is_repo_python = "alpaca-autonomous-microbot" in text and ("python" in text or ".venv" in text)
    is_coinbase_config = "config_coinbase_crypto.yaml" in text
    is_coinbase_broker = "broker coinbase" in text or "broker=coinbase" in text or "coinbase-crypto-bot" in text
    is_main_runner = "main.py" in text or "run_coinbase_crypto.sh" in text

    if is_price_logger:
        classification = "price_logger"
        confidence = "high"
        reason = "price_logger_signature"
    elif is_repo_python and is_coinbase_config and is_main_runner and is_coinbase_broker:
        classification = "trading_bot"
        confidence = "high"
        reason = "coinbase_trading_bot_signature"
    elif is_repo_python and is_coinbase_config and is_main_runner:
        classification = "trading_bot"
        confidence = "medium"
        reason = "coinbase_config_main_runner_signature"
    else:
        classification = "unknown"
        confidence = "low"
        reason = "no_coinbase_trading_signature"

    return {
        "plist_path": str(path),
        "label": label or None,
        "program_arguments": args,
        "working_directory": data.get("WorkingDirectory"),
        "classification": classification,
        "confidence": confidence,
        "recommended_restart_target": label if classification == "trading_bot" else None,
        "reason": reason,
    }


def discover_plists(paths: Iterable[Path]) -> List[Path]:
    found: List[Path] = []
    for base in paths:
        if base.is_file() and base.suffix == ".plist":
            found.append(base)
        elif base.is_dir():
            found.extend(sorted(base.glob("*.plist")))
    return sorted(set(found))


def build_audit(launchagents_dir: Path = DEFAULT_LAUNCHAGENTS_DIR, include_repo_launchd: bool = False) -> Dict[str, Any]:
    search_paths = [launchagents_dir]
    if include_repo_launchd:
        search_paths.append(ROOT / "launchd")
    candidates = [classify_plist(path) for path in discover_plists(search_paths)]
    trading = [item for item in candidates if item.get("classification") == "trading_bot"]
    price_loggers = [item for item in candidates if item.get("classification") == "price_logger"]
    restart_targets = sorted({
        str(item["recommended_restart_target"])
        for item in trading
        if item.get("recommended_restart_target")
    })

    return {
        "verdict": "TRADING_BOT_PLIST_FOUND" if trading else "NO_TRADING_BOT_PLIST_FOUND",
        "launchagents_dir": str(launchagents_dir),
        "include_repo_launchd": include_repo_launchd,
        "candidate_count": len(candidates),
        "trading_bot_found": bool(trading),
        "price_logger_found": bool(price_loggers),
        "recommended_restart_targets": restart_targets,
        "candidates": candidates,
        "safety": {
            "offline_local_plist_inspection_only": True,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "secrets_or_env_read": False,
            "launchctl_mutation": False,
            "process_kill_or_restart": False,
            "state_or_log_mutation": False,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Coinbase LaunchAgent plist candidates without mutation")
    parser.add_argument("--launchagents-dir", type=Path, default=DEFAULT_LAUNCHAGENTS_DIR)
    parser.add_argument(
        "--include-repo-launchd",
        action="store_true",
        help="Also inspect this repo's launchd/ fixture directory",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    audit = build_audit(args.launchagents_dir, include_repo_launchd=args.include_repo_launchd)
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        print("=== Coinbase Trading Process Audit ===")
        print(f"Verdict: {audit['verdict']}")
        print(f"Trading bot found: {audit['trading_bot_found']}")
        print(f"Price logger found: {audit['price_logger_found']}")
        if audit["recommended_restart_targets"]:
            print("Recommended restart target(s): " + ", ".join(audit["recommended_restart_targets"]))
        else:
            print("Recommended restart target(s): none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
