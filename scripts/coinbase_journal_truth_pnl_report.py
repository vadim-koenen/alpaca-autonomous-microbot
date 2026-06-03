#!/usr/bin/env python3
"""
Offline journal-truth P/L report for Coinbase live exits.

This script reads a local CSV journal only. It imports no broker clients, makes
no network calls, places no trades, and mutates no runtime state.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Sequence


DEFAULT_JOURNAL = Path("journal_coinbase_crypto.csv")
SCHEMA_VERSION = "p2-025c.coinbase_journal_truth_pnl.v1"


@dataclass
class Bucket:
    total_closed_cycles: int = 0
    winning_cycles: int = 0
    losing_cycles: int = 0
    breakeven_cycles: int = 0
    gross_pnl_sum: Decimal = Decimal("0")
    fees_sum: Decimal = Decimal("0")
    net_pnl_sum: Decimal = Decimal("0")

    def add(self, gross: Decimal, fees: Decimal, net: Decimal) -> None:
        self.total_closed_cycles += 1
        self.gross_pnl_sum += gross
        self.fees_sum += fees
        self.net_pnl_sum += net
        if net > 0:
            self.winning_cycles += 1
        elif net < 0:
            self.losing_cycles += 1
        else:
            self.breakeven_cycles += 1


@dataclass
class Accumulator:
    summary: Bucket = field(default_factory=Bucket)
    by_strategy: MutableMapping[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    by_symbol: MutableMapping[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    by_exit_reason: MutableMapping[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))
    timestamps: List[str] = field(default_factory=list)
    skipped_rows: MutableMapping[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )


def _decimal(value: Optional[str]) -> Decimal:
    text = (value or "").strip()
    if not text:
        raise InvalidOperation("blank numeric value")
    return Decimal(text)


def _number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0000000001")))


def _win_rate(bucket: Bucket) -> float:
    if bucket.total_closed_cycles == 0:
        return 0.0
    return round(bucket.winning_cycles / bucket.total_closed_cycles, 6)


def _bucket_payload(bucket: Bucket) -> Dict[str, Any]:
    return {
        "total_closed_cycles": bucket.total_closed_cycles,
        "winning_cycles": bucket.winning_cycles,
        "losing_cycles": bucket.losing_cycles,
        "breakeven_cycles": bucket.breakeven_cycles,
        "win_rate": _win_rate(bucket),
        "gross_pnl_sum": _number(bucket.gross_pnl_sum),
        "fees_sum": _number(bucket.fees_sum),
        "net_pnl_sum": _number(bucket.net_pnl_sum),
    }


def _sorted_breakdown(buckets: MutableMapping[str, Bucket]) -> Dict[str, Dict[str, Any]]:
    return {
        key: _bucket_payload(bucket)
        for key, bucket in sorted(
            buckets.items(),
            key=lambda item: (-item[1].total_closed_cycles, item[0]),
        )
    }


def _clean_row(row: Dict[str, Optional[str]]) -> Dict[str, str]:
    return {
        (key or "").strip(): (value or "").strip()
        for key, value in row.items()
        if key is not None
    }


def _is_blank(row: Dict[str, Optional[str]]) -> bool:
    return not row or all(not (value or "").strip() for value in row.values() if value is not None)


def normalize_exit_reason(reason: str) -> str:
    text = (reason or "").strip()
    lower = text.lower()
    if not text:
        return "unspecified"
    if "max hold time" in lower:
        return "max hold time 90min exceeded"
    if "stop-loss" in lower or "stop loss" in lower:
        return "stop-loss hit"
    if "take-profit" in lower or "take profit" in lower:
        return "take-profit hit"
    return text.split("(", 1)[0].strip() or "unspecified"


def _iter_journal_rows(path: Path) -> Iterable[Dict[str, Optional[str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def build_journal_truth_report(journal_path: Path = DEFAULT_JOURNAL) -> Dict[str, Any]:
    path = Path(journal_path)
    acc = Accumulator()
    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "offline_journal_truth",
        "journal_path": str(path),
        "journal_found": path.exists(),
        "readout_class": "journal_recorded_broker_backed",
        "profit_readout": "unsafe_to_aggregate",
        "journal_recorded_profit_readout": "journal_recorded_loss_control_signal",
        "numeric_safe_direct_capture_available": False,
        "numeric_safe_direct_capture_note": (
            "Journal-recorded broker-backed P/L is adequate for operator caution, "
            "but it does not unlock the stricter direct-capture scaling gate."
        ),
        "trade_permission": "none",
        "aggregation_allowed": False,
        "scaling_allowed": False,
        "risk_increase": "not_approved",
    }

    if not path.exists():
        report.update(
            {
                "summary": _bucket_payload(acc.summary),
                "date_range": {"start": None, "end": None},
                "by_strategy": {},
                "by_symbol": {},
                "by_exit_reason": {},
                "dominant_exit_reason": None,
                "skipped_rows": dict(acc.skipped_rows),
                "verdict": "JOURNAL_NOT_FOUND",
            }
        )
        return report

    try:
        rows = list(_iter_journal_rows(path))
    except (OSError, csv.Error) as exc:
        report.update(
            {
                "summary": _bucket_payload(acc.summary),
                "date_range": {"start": None, "end": None},
                "by_strategy": {},
                "by_symbol": {},
                "by_exit_reason": {},
                "dominant_exit_reason": None,
                "skipped_rows": {"read_error": 1},
                "read_error": str(exc),
                "verdict": "JOURNAL_READ_ERROR",
            }
        )
        return report

    for raw in rows:
        if _is_blank(raw):
            acc.skipped_rows["blank"] += 1
            continue
        if None in raw.values() or None in raw.keys():
            acc.skipped_rows["malformed_or_short"] += 1
            continue

        row = _clean_row(raw)
        mode = row.get("mode", "").lower()
        action = row.get("action", "").upper()
        decision = row.get("decision", "").upper()
        if mode != "live":
            acc.skipped_rows["non_live"] += 1
            continue
        if action in {"WARN", "ERROR"} or decision in {"WARN", "ERROR"}:
            acc.skipped_rows["warn_or_error"] += 1
            continue
        if action != "EXIT":
            acc.skipped_rows["non_exit"] += 1
            continue

        try:
            gross = _decimal(row.get("gross_pnl"))
            fees = _decimal(row.get("fees_paid"))
            net = _decimal(row.get("pnl_usd"))
        except InvalidOperation:
            acc.skipped_rows["malformed_numeric"] += 1
            continue

        strategy = row.get("strategy") or "unknown_strategy"
        symbol = row.get("symbol") or "unknown_symbol"
        reason = normalize_exit_reason(row.get("reason", ""))
        timestamp = row.get("timestamp", "")

        acc.summary.add(gross, fees, net)
        acc.by_strategy[strategy].add(gross, fees, net)
        acc.by_symbol[symbol].add(gross, fees, net)
        acc.by_exit_reason[reason].add(gross, fees, net)
        if timestamp:
            acc.timestamps.append(timestamp)

    dominant_exit_reason = None
    if acc.by_exit_reason:
        dominant_exit_reason = max(
            acc.by_exit_reason.items(),
            key=lambda item: (item[1].total_closed_cycles, item[0]),
        )[0]

    timestamps = sorted(acc.timestamps)
    report.update(
        {
            "summary": _bucket_payload(acc.summary),
            "date_range": {
                "start": timestamps[0] if timestamps else None,
                "end": timestamps[-1] if timestamps else None,
            },
            "by_strategy": _sorted_breakdown(acc.by_strategy),
            "by_symbol": _sorted_breakdown(acc.by_symbol),
            "by_exit_reason": _sorted_breakdown(acc.by_exit_reason),
            "dominant_exit_reason": dominant_exit_reason,
            "skipped_rows": dict(sorted(acc.skipped_rows.items())),
            "verdict": "JOURNAL_LOSS_CONTROL_READOUT_READY",
        }
    )
    return report


def _print_text(report: Dict[str, Any]) -> None:
    summary = report["summary"]
    print("=== Coinbase Journal-Truth P/L Report ===")
    print(f"Readout class: {report['readout_class']}")
    print(f"Numeric-safe direct capture available: {report['numeric_safe_direct_capture_available']}")
    print(f"Trade permission: {report['trade_permission']}")
    print(f"Risk increase: {report['risk_increase']}")
    print(f"Scaling allowed: {report['scaling_allowed']}")
    print(f"Closed cycles: {summary['total_closed_cycles']}")
    print(
        f"Wins/Losses/Breakeven: {summary['winning_cycles']}/"
        f"{summary['losing_cycles']}/{summary['breakeven_cycles']}"
    )
    print(f"Win rate: {summary['win_rate']:.6f}")
    print(f"Gross P/L: {summary['gross_pnl_sum']:.10f}")
    print(f"Fees: {summary['fees_sum']:.10f}")
    print(f"Net P/L: {summary['net_pnl_sum']:.10f}")
    print(f"Dominant exit reason: {report['dominant_exit_reason']}")
    print("Per-strategy net P/L:")
    for strategy, row in report["by_strategy"].items():
        print(f"  {strategy}: {row['net_pnl_sum']:.10f} ({row['total_closed_cycles']} cycles)")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase journal-truth P/L report")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL, help="Local Coinbase CSV journal path")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    report = build_journal_truth_report(args.journal)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
