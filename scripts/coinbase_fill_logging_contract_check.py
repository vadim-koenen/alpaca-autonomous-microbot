#!/usr/bin/env python3
"""
ADVISORY ONLY — Coinbase immutable fill logging contract checker.

Read-only local CSV contract validation. This script does not call broker APIs,
does not read .env, does not place orders, does not modify config/state/runtime,
and does not affect live trading behavior.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_FILL_LOG = Path("logs/coinbase_fills.csv")

REQUIRED_COLUMNS: Tuple[str, ...] = (
    "schema_version",
    "logged_at",
    "source",
    "environment",
    "strategy",
    "cycle_id",
    "position_id",
    "client_order_id",
    "exchange_order_id",
    "product_id",
    "symbol",
    "side",
    "order_type",
    "order_status",
    "fill_status",
    "filled_size",
    "average_filled_price",
    "gross_quote_value",
    "fee_amount",
    "fee_currency",
    "net_quote_value",
    "created_at",
    "filled_at",
    "raw_event_type",
    "notes",
)

NUMERIC_COLUMNS: Tuple[str, ...] = (
    "filled_size",
    "average_filled_price",
    "gross_quote_value",
    "fee_amount",
    "net_quote_value",
)

VALID_SIDES = {"buy", "sell"}
VALID_FILL_STATUSES = {"filled", "partial", "canceled", "cancelled", "rejected", "unknown"}


@dataclass(frozen=True)
class ContractResult:
    status: str
    path: Path
    row_count: int
    missing_columns: Tuple[str, ...]
    extra_columns: Tuple[str, ...]
    warnings: Tuple[str, ...]
    errors: Tuple[str, ...]


def normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def parse_float(value: str) -> Optional[float]:
    text = str(value or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def read_csv(path: Path) -> Tuple[Tuple[str, ...], List[Dict[str, str]]]:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = path.read_text(encoding="latin-1")

    if not content.strip():
        return tuple(), []

    reader = csv.DictReader(content.splitlines())
    headers = tuple(normalize_header(header) for header in (reader.fieldnames or []))
    rows: List[Dict[str, str]] = []
    for raw in reader:
        rows.append({normalize_header(k): (v.strip() if isinstance(v, str) else "") for k, v in raw.items() if k is not None})
    return headers, rows


def validate_fill_log(path: Path) -> ContractResult:
    path = path.resolve()

    if not path.exists():
        return ContractResult(
            status="MISSING",
            path=path,
            row_count=0,
            missing_columns=REQUIRED_COLUMNS,
            extra_columns=tuple(),
            warnings=("Fill log does not exist yet. This is expected before implementation.",),
            errors=tuple(),
        )

    if not path.is_file():
        return ContractResult(
            status="FAIL",
            path=path,
            row_count=0,
            missing_columns=REQUIRED_COLUMNS,
            extra_columns=tuple(),
            warnings=tuple(),
            errors=("Path exists but is not a file.",),
        )

    headers, rows = read_csv(path)
    header_set = set(headers)
    required_set = set(REQUIRED_COLUMNS)

    missing = tuple(column for column in REQUIRED_COLUMNS if column not in header_set)
    extra = tuple(column for column in headers if column not in required_set)

    errors: List[str] = []
    warnings: List[str] = []

    if missing:
        errors.append(f"Missing required columns: {', '.join(missing)}")

    if extra:
        warnings.append(f"Extra columns present: {', '.join(extra)}")

    for index, row in enumerate(rows, start=2):
        side = row.get("side", "").strip().lower()
        if side and side not in VALID_SIDES:
            errors.append(f"Row {index}: invalid side={side!r}")

        fill_status = row.get("fill_status", "").strip().lower()
        if fill_status and fill_status not in VALID_FILL_STATUSES:
            warnings.append(f"Row {index}: unexpected fill_status={fill_status!r}")

        for column in NUMERIC_COLUMNS:
            value = row.get(column, "")
            if value == "":
                errors.append(f"Row {index}: missing numeric field {column}")
            elif parse_float(value) is None:
                errors.append(f"Row {index}: invalid numeric field {column}={value!r}")

        if not row.get("exchange_order_id") and not row.get("client_order_id"):
            errors.append(f"Row {index}: missing both exchange_order_id and client_order_id")

        if not row.get("cycle_id"):
            warnings.append(f"Row {index}: missing cycle_id; buy/sell pairing may be degraded")

    status = "FAIL" if errors else "PASS"
    return ContractResult(
        status=status,
        path=path,
        row_count=len(rows),
        missing_columns=missing,
        extra_columns=extra,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def render(result: ContractResult) -> str:
    lines: List[str] = []
    lines.append("=== Coinbase Immutable Fill Logging Contract Check ===")
    lines.append("ADVISORY ONLY / READ ONLY / LOCAL CSV VALIDATION ONLY")
    lines.append(f"Path: {result.path}")
    lines.append(f"Status: {result.status}")
    lines.append(f"Rows: {result.row_count}")
    lines.append("")

    lines.append("--- Required columns ---")
    for column in REQUIRED_COLUMNS:
        marker = "MISSING" if column in result.missing_columns else "OK"
        lines.append(f"{marker:7} {column}")
    lines.append("")

    if result.extra_columns:
        lines.append("--- Extra columns ---")
        for column in result.extra_columns:
            lines.append(column)
        lines.append("")

    if result.warnings:
        lines.append("--- Warnings ---")
        for warning in result.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    if result.errors:
        lines.append("--- Errors ---")
        for error in result.errors:
            lines.append(f"- {error}")
        lines.append("")

    if result.status == "MISSING":
        lines.append("Verdict: No fill log exists yet. Do not infer realized P/L from journal exit intent rows.")
    elif result.status == "PASS":
        lines.append("Verdict: Fill log satisfies the minimum contract. Realized P/L reconstruction may be evaluated by a separate report.")
    else:
        lines.append("Verdict: Fill log does not satisfy the minimum contract. Realized P/L remains unsafe.")

    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Advisory-only Coinbase fill logging contract checker")
    parser.add_argument("--path", default=str(DEFAULT_FILL_LOG), help="Fill log CSV path to validate")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on FAIL. MISSING remains advisory/zero.")
    args = parser.parse_args(argv)

    result = validate_fill_log(Path(args.path))
    print(render(result), end="")

    if args.strict and result.status == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
