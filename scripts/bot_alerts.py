#!/usr/bin/env python3
"""Small file-based operational alert sink with secret-safe context."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


SECRET_KEY_PATTERN = re.compile(
    r"(secret|token|password|private|authorization|bearer|api[_-]?key|cb-access|jwt)",
    re.IGNORECASE,
)

ACCOUNT_KEY_PATTERN = re.compile(
    r"(account[_-]?id|account[_-]?number|account[_-]?num|account)",
    re.IGNORECASE,
)


def _redact(value: Any, key: str = "") -> Any:
    if SECRET_KEY_PATTERN.search(key):
        return "<REDACTED>"
    if ACCOUNT_KEY_PATTERN.search(key) and value is not None:
        if isinstance(value, str):
            if len(value) > 4:
                return "****" + value[-4:]
            return "[REDACTED_ACCOUNT]"
        return "[REDACTED_ACCOUNT]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(
            r"(?i)(authorization|bearer|api[_-]?key|secret|token|password)\s*[:=]\s*\S+",
            r"\1=<REDACTED>",
            value,
        )
        # Redact UUID-like patterns
        value = re.sub(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{8}([0-9a-fA-F]{4})\b",
            r"****\1",
            value,
        )
    return value


def _send_macos_notification(level: str, message: str, context: Optional[Dict[str, Any]] = None) -> str:
    if os.environ.get("ENABLE_MACOS_ALERTS") != "1":
        return "dry_run"

    # AppleScript string escaping
    def escape(s: str) -> str:
        return str(s).replace("\\", "\\\\").replace('"', '\\"')

    esc_msg = escape(message)
    esc_title = escape(f"Bot Alert: {level}")
    code = (context or {}).get("code", "Notification") if context else "Notification"
    esc_subtitle = escape(str(code))

    script = f'display notification "{esc_msg}" with title "{esc_title}" subtitle "{esc_subtitle}"'
    try:
        import subprocess
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False, timeout=5)
        if res.returncode == 0:
            return "sent"
        else:
            return f"failed_code_{res.returncode}"
    except Exception as e:
        return f"failed: {e}"


def alert(
    level: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    *,
    reports_root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Write a structured and human-readable local alert."""
    now = now or datetime.now(timezone.utc)
    root = reports_root or Path(__file__).resolve().parents[1] / "reports"
    alerts_dir = root / "alerts"
    jsonl_path = alerts_dir / "alerts.jsonl"
    text_path = alerts_dir / "alerts.log"
    payload = {
        "timestamp_utc": now.astimezone(timezone.utc).isoformat(),
        "level": str(level).upper(),
        "message": str(_redact(message)),
        "context": _redact(context or {}),
    }
    
    # Send macOS notification
    macos_status = _send_macos_notification(payload["level"], payload["message"], payload["context"])

    result = {
        "file_alert_written": False,
        "email_status": "email_not_configured",
        "macos_notification_status": macos_status,
        "jsonl_path": str(jsonl_path),
        "text_path": str(text_path),
        "payload": payload,
    }
    try:
        alerts_dir.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        with text_path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{payload['timestamp_utc']} | {payload['level']} | "
                f"{payload['message']} | {json.dumps(payload['context'], sort_keys=True)}\n"
            )
        result["file_alert_written"] = True
    except OSError as exc:
        result["file_error"] = str(exc)
    return result


__all__ = ["alert"]

