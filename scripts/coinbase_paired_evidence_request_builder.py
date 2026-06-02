#!/usr/bin/env python3
"""
P2-022B - Offline Coinbase paired evidence request builder.

Builds a deterministic read-only capture request from local journal CSV rows.
It does not import broker clients, read environment files, call live APIs, or
perform any order activity.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence


UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
PROFIT_SYMBOLS = ("BTC/USD", "ETH/USD")
EXCLUDED_PROFIT_SYMBOLS = ("SOL/USD",)
ENTRY_ACTIONS = {"BUY", "ENTRY"}
EXIT_ACTIONS = {"EXIT", "SELL"}
IGNORED_DECISIONS = {"SKIPPED", "REJECTED", "FAILED"}


@dataclass(frozen=True)
class JournalEvent:
    journal: str
    row_number: int
    timestamp: str
    parsed_timestamp: datetime
    symbol: str
    action: str
    decision: str
    order_id: str
    client_order_id: str
    reason: str
    status: str


def _key_name(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_row(row: Dict[str, str]) -> Dict[str, str]:
    return {
        _key_name(key): (value.strip() if isinstance(value, str) else "")
        for key, value in row.items()
        if key is not None
    }


def _first(row: Dict[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        value = row.get(_key_name(key), "")
        if value:
            return str(value).strip()
    return ""


def _parse_time(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("-", "/")


def _product_id(symbol: str) -> str:
    return _normalize_symbol(symbol).replace("/", "-")


def _is_uuid(value: str) -> bool:
    return bool(UUID_RE.match(str(value or "").strip()))


def _event_role(event: JournalEvent) -> str:
    action = event.action.upper()
    if action in ENTRY_ACTIONS:
        return "entry"
    if action in EXIT_ACTIONS:
        return "exit"
    return "ignore"


def _source_row(event: JournalEvent) -> Dict[str, Any]:
    return {
        "journal": event.journal,
        "row_number": event.row_number,
        "timestamp": event.timestamp,
        "symbol": event.symbol,
        "action": event.action,
        "decision": event.decision,
        "order_id": event.order_id,
        "client_order_id": event.client_order_id,
        "status": event.status,
        "reason": event.reason,
    }


def _cycle_id(symbol: str, sequence: int) -> str:
    return f"{_product_id(symbol).lower()}-paired-cycle-{sequence:03d}"


def _build_cycle(entry: JournalEvent, exit_event: JournalEvent, sequence: int) -> Dict[str, Any]:
    symbol = _normalize_symbol(entry.symbol)
    return {
        "cycle_id": _cycle_id(symbol, sequence),
        "product_id": _product_id(symbol),
        "order_ids": {
            "entry": entry.order_id,
            "exit": exit_event.order_id,
        },
        "date_window": {
            "start": entry.timestamp,
            "end": exit_event.timestamp,
        },
        "source_rows": {
            "entry": _source_row(entry),
            "exit": _source_row(exit_event),
        },
    }


def read_journal_events(paths: Sequence[Path]) -> List[JournalEvent]:
    events: List[JournalEvent] = []
    for path in paths:
        if not path or not path.exists():
            continue
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                for row_number, raw_row in enumerate(reader, start=2):
                    row = _normalize_row(raw_row)
                    ts_raw = _first(row, ("timestamp", "ts", "time", "created_at"))
                    parsed_ts = _parse_time(ts_raw)
                    if parsed_ts is None:
                        continue
                    events.append(
                        JournalEvent(
                            journal=str(path),
                            row_number=row_number,
                            timestamp=ts_raw,
                            parsed_timestamp=parsed_ts,
                            symbol=_normalize_symbol(_first(row, ("symbol", "product_id", "product"))),
                            action=_first(row, ("action", "side", "event", "type")).upper(),
                            decision=_first(row, ("decision", "status", "order_status")).upper(),
                            order_id=_first(row, ("order_id", "coinbase_order_id")),
                            client_order_id=_first(row, ("client_order_id",)),
                            reason=_first(row, ("reason", "error", "message", "notes")),
                            status=_first(row, ("status", "order_status")),
                        )
                    )
        except Exception:
            continue
    return sorted(events, key=lambda event: (event.parsed_timestamp, event.journal, event.row_number))


def _lookback_filtered(events: Sequence[JournalEvent], lookback_days: int) -> List[JournalEvent]:
    if not events:
        return []
    if lookback_days <= 0:
        return list(events)
    anchor = max(event.parsed_timestamp for event in events)
    cutoff = anchor - timedelta(days=lookback_days)
    return [event for event in events if event.parsed_timestamp >= cutoff]


def build_request(
    *,
    journal: Path,
    secondary_journal: Optional[Path] = None,
    max_cycles: int = 8,
    lookback_days: int = 14,
) -> Dict[str, Any]:
    paths = [journal]
    if secondary_journal is not None:
        paths.append(secondary_journal)
    events = _lookback_filtered(read_journal_events(paths), lookback_days)

    queues: Dict[str, Deque[JournalEvent]] = {symbol: deque() for symbol in PROFIT_SYMBOLS}
    cycles: List[Dict[str, Any]] = []
    uuid_btc_eth_rows = 0
    uuid_profit_rows_by_symbol: Dict[str, int] = {symbol: 0 for symbol in PROFIT_SYMBOLS}
    excluded_symbol_uuid_rows = 0
    ignored_client_order_id_only_rows = 0
    ignored_missing_uuid_order_id_rows = 0
    ignored_manual_review_rows = 0

    for event in events:
        symbol = _normalize_symbol(event.symbol)
        decision = event.decision.upper()
        reason = event.reason.lower()
        role = _event_role(event)

        if "manual_review_position_open" in reason or decision in IGNORED_DECISIONS:
            if "manual_review_position_open" in reason:
                ignored_manual_review_rows += 1
            continue

        if symbol in EXCLUDED_PROFIT_SYMBOLS and _is_uuid(event.order_id):
            excluded_symbol_uuid_rows += 1
            continue

        if symbol not in PROFIT_SYMBOLS or role == "ignore":
            continue

        if not _is_uuid(event.order_id):
            if _is_uuid(event.client_order_id):
                ignored_client_order_id_only_rows += 1
            else:
                ignored_missing_uuid_order_id_rows += 1
            continue

        uuid_btc_eth_rows += 1
        uuid_profit_rows_by_symbol[symbol] += 1

        if role == "entry":
            queues[symbol].append(event)
            continue

        if role == "exit" and queues[symbol]:
            entry = queues[symbol].popleft()
            cycles.append(_build_cycle(entry, event, len(cycles) + 1))

    selected_cycles = cycles[: max(0, max_cycles)]
    unpaired_entries = sum(len(queue) for queue in queues.values())

    return {
        "request_type": "coinbase_paired_order_evidence_capture",
        "schema_version": "p2-022b.v1",
        "cycles": selected_cycles,
        "summary": {
            "paired_cycles_count": len(selected_cycles),
            "candidate_paired_cycles_count": len(cycles),
            "uuid_btc_eth_rows": uuid_btc_eth_rows,
            "uuid_profit_rows_by_symbol": uuid_profit_rows_by_symbol,
            "profit_aggregation_symbols": list(PROFIT_SYMBOLS),
            "excluded_profit_symbols": list(EXCLUDED_PROFIT_SYMBOLS),
            "excluded_symbol_uuid_rows": excluded_symbol_uuid_rows,
            "unpaired_entry_count": unpaired_entries,
            "ignored_client_order_id_only_rows": ignored_client_order_id_only_rows,
            "ignored_missing_uuid_order_id_rows": ignored_missing_uuid_order_id_rows,
            "ignored_manual_review_rows": ignored_manual_review_rows,
            "lookback_days": lookback_days,
            "max_cycles": max_cycles,
        },
        "safety": {
            "read_only_only": True,
            "no_order_cancel_close_modify": True,
            "no_risk_increase": True,
            "no_state_or_log_mutation": True,
            "redact_before_adapter": True,
            "broker_calls_made": False,
            "live_read_only_executed": False,
            "secrets_or_env_read": False,
            "logs_coinbase_fills_written": False,
            "append_coinbase_fill_row_activated": False,
            "profit_readout_real_current": "unsafe_to_aggregate",
            "aggregation_allowed_real_current": False,
            "scaling_allowed": False,
            "risk_increase": "not_approved",
        },
    }


def write_request(payload: Dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase paired evidence request builder")
    parser.add_argument("--journal", required=True, type=Path, help="Primary local Coinbase journal CSV")
    parser.add_argument("--secondary-journal", type=Path, help="Optional secondary local journal CSV")
    parser.add_argument("--output", required=True, type=Path, help="Output request JSON path")
    parser.add_argument("--max-cycles", type=int, default=8, help="Maximum paired cycles to include")
    parser.add_argument("--lookback-days", type=int, default=14, help="Lookback window relative to latest journal row")
    parser.add_argument("--json", action="store_true", help="Print request JSON to stdout")
    args = parser.parse_args(argv)

    payload = build_request(
        journal=args.journal,
        secondary_journal=args.secondary_journal,
        max_cycles=args.max_cycles,
        lookback_days=args.lookback_days,
    )
    write_request(payload, args.output)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        summary = payload["summary"]
        print("=== Coinbase Paired Evidence Request Builder (P2-022B) ===")
        print(f"paired_cycles_count={summary['paired_cycles_count']}")
        print(f"uuid_btc_eth_rows={summary['uuid_btc_eth_rows']}")
        print(f"output={args.output}")
        print("profit_readout_real_current=unsafe_to_aggregate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
