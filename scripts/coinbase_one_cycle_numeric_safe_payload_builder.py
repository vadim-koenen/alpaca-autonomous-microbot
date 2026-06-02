#!/usr/bin/env python3
"""
Build a numeric-safe redacted Coinbase one-cycle evidence payload from local files.

This script is offline-only. It reads supplied JSON files, redacts identifiers
and secret-like fields, preserves broker numeric P/L fields when explicitly
requested, and writes a p2-022c one-cycle payload for the offline adapter/readout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scripts.coinbase_broker_evidence_adapter import ONE_CYCLE_READ_ONLY_SCHEMA
from scripts.redact_broker_payload import redact_payload


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        json_start = text.find("{")
        if json_start > 0:
            text = text[json_start:]
        payload = json.loads(text)
    except Exception as exc:
        return {"_load_error": str(exc), "_source_path": str(path)}
    return payload if isinstance(payload, dict) else {"payload": payload}


def _redacted_order_id(label: str, value: Optional[str]) -> str:
    return f"<REDACTED_{label.upper()}_ORDER_ID>" if value else ""


def build_one_cycle_payload(
    *,
    entry_raw_path: Path,
    exit_raw_path: Path,
    cycle_id: str,
    product_id: str,
    entry_order_id: Optional[str],
    exit_order_id: Optional[str],
    preserve_numeric_pnl_fields: bool,
) -> Dict[str, Any]:
    entry_raw = _safe_load_json(entry_raw_path)
    exit_raw = _safe_load_json(exit_raw_path)
    entry_redacted = redact_payload(
        entry_raw,
        preserve_numeric_pnl_fields=preserve_numeric_pnl_fields,
    )
    exit_redacted = redact_payload(
        exit_raw,
        preserve_numeric_pnl_fields=preserve_numeric_pnl_fields,
    )
    entry_order_id_redacted = _redacted_order_id("entry", entry_order_id)
    exit_order_id_redacted = _redacted_order_id("exit", exit_order_id)

    return {
        "schema_version": ONE_CYCLE_READ_ONLY_SCHEMA,
        "capture_scope": {
            "cycle_id": cycle_id,
            "product_id": product_id,
            "entry_order_id": entry_order_id_redacted,
            "exit_order_id": exit_order_id_redacted,
            "read_only_only": True,
            "numeric_safe_redaction": preserve_numeric_pnl_fields,
            "identifiers_redacted": True,
            "no_order_cancel_close_modify": True,
            "no_state_or_log_mutation": True,
            "no_risk_increase": True,
            "profit_readout_before_resolution": "unsafe_to_aggregate",
        },
        "cycles": [
            {
                "cycle_id": cycle_id,
                "product_id": product_id,
                "entry_order_id": entry_order_id_redacted,
                "exit_order_id": exit_order_id_redacted,
                "entry_broker_payload_redacted": entry_redacted,
                "exit_broker_payload_redacted": exit_redacted,
            }
        ],
        "builder_safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "secrets_or_env_read": False,
            "orders_cancels_closes_modifications": False,
            "state_or_log_mutation": False,
            "fill_logger_activation": False,
            "risk_increase": "not_approved",
            "scaling_allowed": False,
        },
        "redaction_policy": {
            "preserve_numeric_pnl_fields": preserve_numeric_pnl_fields,
            "preserved_numeric_fields": [
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
            ],
            "redacted_identifier_fields": [
                "account_id",
                "client_order_id",
                "entry_id",
                "fill_id",
                "order_id",
                "retail_portfolio_id",
                "trade_id",
                "user_id",
            ],
            "secret_key_fragments_redacted": [
                "api_key",
                "auth",
                "authorization",
                "bearer",
                "key",
                "password",
                "secret",
                "signature",
                "token",
            ],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an offline numeric-safe Coinbase one-cycle evidence payload",
    )
    parser.add_argument("--entry-raw", required=True, type=Path, help="Local raw entry JSON")
    parser.add_argument("--exit-raw", required=True, type=Path, help="Local raw exit JSON")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON path")
    parser.add_argument("--cycle-id", required=True, help="Cycle identifier")
    parser.add_argument("--product-id", required=True, help="Coinbase product ID, for example ETH-USD")
    parser.add_argument("--entry-order-id", required=True, help="Entry order ID; redacted in output")
    parser.add_argument("--exit-order-id", required=True, help="Exit order ID; redacted in output")
    parser.add_argument(
        "--preserve-numeric-pnl-fields",
        action="store_true",
        help="Preserve direct broker numeric P/L fields while redacting identifiers/secrets",
    )
    parser.add_argument("--json", action="store_true", help="Print build summary JSON")
    args = parser.parse_args(argv)

    payload = build_one_cycle_payload(
        entry_raw_path=args.entry_raw,
        exit_raw_path=args.exit_raw,
        cycle_id=args.cycle_id,
        product_id=args.product_id,
        entry_order_id=args.entry_order_id,
        exit_order_id=args.exit_order_id,
        preserve_numeric_pnl_fields=args.preserve_numeric_pnl_fields,
    )
    args.output.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")

    summary = {
        "verdict": "NUMERIC_SAFE_PAYLOAD_BUILT",
        "output": str(args.output),
        "schema_version": payload["schema_version"],
        "cycle_id": args.cycle_id,
        "product_id": args.product_id,
        "preserve_numeric_pnl_fields": args.preserve_numeric_pnl_fields,
        "identifiers_redacted": True,
        "scaling_allowed": False,
        "risk_increase": "not_approved",
        "safety": payload["builder_safety"],
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("=== Coinbase Numeric-Safe One-Cycle Payload Builder ===")
        print(f"Verdict: {summary['verdict']}")
        print(f"Output: {summary['output']}")
        print(f"Schema: {summary['schema_version']}")
        print(f"Scaling allowed: {summary['scaling_allowed']}")
        print(f"Risk increase: {summary['risk_increase']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
