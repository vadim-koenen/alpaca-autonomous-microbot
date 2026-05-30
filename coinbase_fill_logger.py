"""Append-only Coinbase fill/proceeds/fee logger.

P2-011A scaffold only:
- no Coinbase API calls
- no strategy/risk/config behavior changes
- no execution-path hook
- append-only CSV utility for immutable fill/proceeds/fee facts
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_COINBASE_FILLS_CSV = Path("logs/coinbase_fills.csv")

COINBASE_FILL_SCHEMA_VERSION = "p2_011a_v1"

COINBASE_FILL_FIELDS = (
    "schema_version",
    "captured_at_utc",
    "source",
    "broker",
    "account_mode",
    "product_id",
    "side",
    "order_id",
    "client_order_id",
    "status",
    "created_time",
    "completion_time",
    "filled_size",
    "average_filled_price",
    "gross_quote_value",
    "fee_amount",
    "fee_currency",
    "net_quote_value",
    "liquidity_indicator",
    "raw_order_response_json",
    "raw_fill_response_json",
    "reconstruction_status",
    "notes",
)


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp suitable for immutable logs."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_json_payload(value: Any) -> str:
    """Normalize raw broker/fill payloads into deterministic JSON strings."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def build_coinbase_fill_row(
    *,
    source: str,
    product_id: str,
    side: str,
    order_id: str,
    status: str,
    captured_at_utc: str | None = None,
    broker: str = "coinbase",
    account_mode: str = "",
    client_order_id: str = "",
    created_time: str = "",
    completion_time: str = "",
    filled_size: str = "",
    average_filled_price: str = "",
    gross_quote_value: str = "",
    fee_amount: str = "",
    fee_currency: str = "",
    net_quote_value: str = "",
    liquidity_indicator: str = "",
    raw_order_response_json: Any = "",
    raw_fill_response_json: Any = "",
    reconstruction_status: str = "unreconciled",
    notes: str = "",
) -> dict[str, str]:
    """Build a schema-aligned Coinbase fill log row."""
    return {
        "schema_version": COINBASE_FILL_SCHEMA_VERSION,
        "captured_at_utc": captured_at_utc or utc_now_iso(),
        "source": str(source),
        "broker": str(broker),
        "account_mode": str(account_mode),
        "product_id": str(product_id),
        "side": str(side),
        "order_id": str(order_id),
        "client_order_id": str(client_order_id),
        "status": str(status),
        "created_time": str(created_time),
        "completion_time": str(completion_time),
        "filled_size": str(filled_size),
        "average_filled_price": str(average_filled_price),
        "gross_quote_value": str(gross_quote_value),
        "fee_amount": str(fee_amount),
        "fee_currency": str(fee_currency),
        "net_quote_value": str(net_quote_value),
        "liquidity_indicator": str(liquidity_indicator),
        "raw_order_response_json": normalize_json_payload(raw_order_response_json),
        "raw_fill_response_json": normalize_json_payload(raw_fill_response_json),
        "reconstruction_status": str(reconstruction_status),
        "notes": str(notes),
    }


def _validate_row_schema(row: Mapping[str, Any]) -> None:
    expected = set(COINBASE_FILL_FIELDS)
    actual = set(row.keys())
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        raise ValueError(
            "Coinbase fill row does not match schema. "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )


def _validate_existing_header(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        existing_header = next(reader, None)

    expected_header = list(COINBASE_FILL_FIELDS)
    if existing_header != expected_header:
        raise ValueError(
            f"Existing Coinbase fill log header mismatch at {path}. "
            "Refusing to append to avoid corrupting immutable fill history."
        )


def append_coinbase_fill_row(
    row: Mapping[str, Any],
    *,
    path: str | Path = DEFAULT_COINBASE_FILLS_CSV,
) -> Path:
    """Append one immutable Coinbase fill row to CSV.

    Creates parent directory and header when needed. Never truncates an existing
    file and refuses to append if the existing header does not match the schema.
    """
    _validate_row_schema(row)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_existing_header(output_path)

    should_write_header = not output_path.exists() or output_path.stat().st_size == 0

    with output_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COINBASE_FILL_FIELDS))
        if should_write_header:
            writer.writeheader()
        writer.writerow({field: str(row.get(field, "")) for field in COINBASE_FILL_FIELDS})

    return output_path
