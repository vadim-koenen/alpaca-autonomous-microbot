#!/usr/bin/env python3
"""
P2-019F — Broker Payload Redaction Helper (GREEN, offline only).

Reads JSON from stdin or a file and outputs a redacted version.
No network, no .env, no broker imports, stdout only by default.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SENSITIVE_PATTERNS = [
    r"account_id", r"account_uuid", r"portfolio_id", r"user_id",
    r"api_key", r"secret", r"token", r"bearer", r"authorization",
    r"client_order_id", r"wallet", r"deposit_address",
]

REDACTED = "<REDACTED>"


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(re.search(p, k) for p in SENSITIVE_PATTERNS)


def _redact_value(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: REDACTED if _is_sensitive(k) else _redact_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_redact_value(item) for item in v]
    if isinstance(v, str) and len(v) > 20:
        return "..." + v[-6:]
    return v


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: REDACTED if _is_sensitive(k) else _redact_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_value(item) for item in obj]
    return obj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="Input JSON file (default: stdin)")
    parser.add_argument("--output", type=Path, help="Output file (default: stdout)")
    args = parser.parse_args()

    if args.input:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        data = json.load(sys.stdin)

    redacted = redact(data)

    if args.output:
        args.output.write_text(json.dumps(redacted, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(redacted, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
