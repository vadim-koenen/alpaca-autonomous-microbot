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
from typing import Any, Optional

SENSITIVE_PATTERNS = [
    r"account_id", r"account_uuid", r"portfolio_id", r"user_id",
    r"api_key", r"secret", r"token", r"bearer", r"authorization",
    r"client_order_id", r"wallet", r"deposit_address",
]

REDACTED = "<REDACTED>"

NUMERIC_PNL_FIELDS = {
    "average_filled_price",
    "commission",
    "commission_detail_total",
    "fee",
    "filled_size",
    "filled_value",
    "price",
    "proceeds",
    "size",
    "size_in_quote",
    "total_fee",
    "total_fees",
}

SAFE_CONTEXT_FIELDS = {
    "broker_calls_made",
    "broker_methods_attempted",
    "direct_sell_proceeds_present",
    "generated_at",
    "has_average_filled_price",
    "has_fee",
    "has_filled_size",
    "has_filled_value",
    "has_liquidity_indicator",
    "has_price",
    "has_settled",
    "has_size",
    "has_stable_id",
    "has_total_fees",
    "leg_type",
    "liquidity_indicator",
    "live_read_only_requested",
    "logger_readiness_blocked",
    "normalized_status",
    "order_mutation_methods_attempted",
    "per_fill_fees_present",
    "product_id",
    "raw_fills_count",
    "read_only_only",
    "schema_version",
    "settled",
    "side",
    "stable_per_fill_ids_present",
    "status",
    "symbol",
    "trade_time",
}

IDENTIFIER_LABELS = {
    "account_id": "ACCOUNT_ID",
    "account_uuid": "ACCOUNT_ID",
    "client_order_id": "CLIENT_ORDER_ID",
    "entry_id": "ENTRY_ID",
    "entry_order_id": "ENTRY_ORDER_ID",
    "exit_order_id": "EXIT_ORDER_ID",
    "fill_id": "FILL_ID",
    "id": "ID",
    "order_id": "ORDER_ID",
    "portfolio_id": "PORTFOLIO_ID",
    "retail_portfolio_id": "PORTFOLIO_ID",
    "stable_id_value": "FILL_ID",
    "trade_id": "TRADE_ID",
    "user_id": "USER_ID",
}

SECRET_KEY_FRAGMENTS = (
    "api_key",
    "auth",
    "authorization",
    "bearer",
    "key",
    "password",
    "secret",
    "signature",
    "token",
)

SAFE_ID_KEYS = {"product_id"}
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
LONG_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{24,}$")
NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)$")


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(re.search(p, k) for p in SENSITIVE_PATTERNS)


def _is_numberish(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(NUMBER_RE.match(value.strip()))
    return False


def _secret_key(key: str) -> bool:
    k = key.lower()
    return any(fragment in k for fragment in SECRET_KEY_FRAGMENTS)


def _identifier_label(key: str) -> Optional[str]:
    k = key.lower()
    if k in SAFE_ID_KEYS:
        return None
    if k in IDENTIFIER_LABELS:
        return IDENTIFIER_LABELS[k]
    if k.endswith("_id"):
        return k.upper()
    return None


def _looks_like_identifier(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if UUID_RE.match(text):
        return True
    if LONG_IDENTIFIER_RE.match(text) and not _is_numberish(text):
        return True
    return False


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


def _redact_numeric_safe_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {
            child_key: _redact_numeric_safe_value(child_key, child_value)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_numeric_safe_value(key, item) for item in value]

    lower_key = key.lower()
    if lower_key in NUMERIC_PNL_FIELDS:
        return value if _is_numberish(value) else "<REDACTED_NON_NUMERIC_BROKER_FIELD>"

    if lower_key in SAFE_CONTEXT_FIELDS:
        return value

    if _secret_key(lower_key):
        return "<REDACTED_SECRET>"

    identifier_label = _identifier_label(lower_key)
    if identifier_label:
        return f"<REDACTED_{identifier_label}>"

    if isinstance(value, str) and _looks_like_identifier(value):
        return "<REDACTED_IDENTIFIER>"

    return value


def redact_numeric_safe(obj: Any) -> Any:
    """Redact identifiers/secrets while preserving broker numeric P/L fields."""
    if isinstance(obj, dict):
        return {
            key: _redact_numeric_safe_value(key, value)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_numeric_safe_value("", item) for item in obj]
    return obj


def redact_payload(obj: Any, *, preserve_numeric_pnl_fields: bool = False) -> Any:
    if preserve_numeric_pnl_fields:
        return redact_numeric_safe(obj)
    return redact(obj)


def _load_json_text(text: str) -> Any:
    json_start = text.find("{")
    if json_start > 0:
        text = text[json_start:]
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="Input JSON file (default: stdin)")
    parser.add_argument("--output", type=Path, help="Output file (default: stdout)")
    parser.add_argument(
        "--preserve-numeric-pnl-fields",
        action="store_true",
        help="Preserve direct broker numeric P/L fields while redacting identifiers/secrets",
    )
    args = parser.parse_args()

    if args.input:
        data = _load_json_text(args.input.read_text(encoding="utf-8"))
    else:
        data = _load_json_text(sys.stdin.read())

    redacted = redact_payload(
        data,
        preserve_numeric_pnl_fields=args.preserve_numeric_pnl_fields,
    )

    if args.output:
        args.output.write_text(json.dumps(redacted, indent=2, default=str), encoding="utf-8")
    else:
        print(json.dumps(redacted, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
