#!/usr/bin/env python3
"""
ADVISORY ONLY — Read-only Coinbase Operator Status Aggregator (P2-014E).

One command that gives the operator a clear top-level view by safely aggregating
existing local-only reports and data:

- Fill / proceeds / P&L reconciliation status
- Open / orphan / dropped position status (with special emphasis on SOL/USD blocker)
- Prediction outcome price data coverage
- Synthesized top verdict (OK / WARN / BLOCKED)
- Profit/readout classification (direct / reconstructed / estimated / unavailable / unsafe_to_aggregate)
- Explicit blockers
- Explicit next recommended action
- --json for machines / dashboards

This script is 100% read-only and local-only.
It never calls broker APIs, never reads .env, never makes network calls,
never places/cancels/modifies orders, never writes files (especially not
logs/coinbase_fills.csv), and never calls append_coinbase_fill_row.

It reuses the existing report functions from:
  - scripts/coinbase_fill_proceeds_reconciliation_report.py
  - scripts/coinbase_open_orphan_position_status.py
  - prediction_telemetry.py (discover_local_price_coverage)

Do not modify the underlying reports when improving this aggregator.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make the script runnable both as `python3 scripts/xxx.py` and when imported.
# This allows safe reuse of sibling report functions without breaking the
# "run as standalone" contract used throughout the codebase.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

# Safe imports of existing pure/read-only report functions
try:
    from scripts.coinbase_fill_proceeds_reconciliation_report import run_report as run_proceeds_report
except Exception:
    run_proceeds_report = None

try:
    from scripts.coinbase_open_orphan_position_status import (
        run_report as run_orphan_report,
        run_report_json as run_orphan_report_json,
    )
except Exception:
    run_orphan_report = None
    run_orphan_report_json = None

try:
    from prediction_telemetry import discover_local_price_coverage
except Exception:
    discover_local_price_coverage = None

try:
    from scripts.coinbase_stale_blocker_watchdog import (
        run_stale_blocker_report_json as run_stale_blocker_json,
    )
except Exception:
    run_stale_blocker_json = None


def _safe_run_proceeds(root: Path) -> str:
    if run_proceeds_report is None:
        return "PROCEEDS_REPORT_UNAVAILABLE (import failed)"
    try:
        return run_proceeds_report(root)
    except Exception as e:
        return f"PROCEEDS_REPORT_ERROR: {e}"


def _safe_run_orphan_text(root: Path) -> str:
    if run_orphan_report is None:
        return "ORPHAN_REPORT_UNAVAILABLE (import failed)"
    try:
        return run_orphan_report(root)
    except Exception as e:
        return f"ORPHAN_REPORT_ERROR: {e}"


def _safe_run_orphan_json(root: Path) -> Dict[str, Any]:
    if run_orphan_report_json is None:
        return {"error": "ORPHAN_JSON_UNAVAILABLE"}
    try:
        return run_orphan_report_json(root)
    except Exception as e:
        return {"error": f"ORPHAN_JSON_ERROR: {e}"}


def _safe_price_coverage(telemetry_path: Optional[Path] = None) -> Dict[str, Any]:
    if discover_local_price_coverage is None:
        return {"error": "PRICE_COVERAGE_UNAVAILABLE (import failed)"}
    try:
        return discover_local_price_coverage(telemetry_path)
    except Exception as e:
        return {"error": f"PRICE_COVERAGE_ERROR: {e}"}


def _safe_stale_blocker(root: Path) -> Dict[str, Any]:
    if run_stale_blocker_json is None:
        return {"error": "STALE_BLOCKER_REPORT_UNAVAILABLE"}
    try:
        return run_stale_blocker_json(root)
    except Exception as e:
        return {"error": f"STALE_BLOCKER_ERROR: {e}"}


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "y"):
            return True
        if text in ("false", "0", "no", "n"):
            return False
    return None


def _external_inventory_records(root: Path) -> Dict[str, Dict[str, Any]]:
    data = _safe_load_json(root / "state" / "coinbase" / "external_inventory.json")
    if isinstance(data.get("external_inventory"), dict):
        data = data["external_inventory"]
    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}


def _is_external_staked_record(record: Dict[str, Any]) -> bool:
    classification = str(record.get("external_inventory_classification") or "").lower()
    return (
        "external" in classification
        and "staked" in classification
        and _as_bool(record.get("staked_external_position")) is True
        and _as_bool(record.get("bot_inventory")) is False
        and _as_bool(record.get("tradable_by_bot")) is False
        and _as_bool(record.get("manual_close_allowed")) is False
        and _as_bool(record.get("blocks_new_entries")) is not True
    )


def _external_sol_record(root: Path) -> Optional[Dict[str, Any]]:
    for symbol, record in _external_inventory_records(root).items():
        record_symbol = str(record.get("symbol") or symbol).upper().replace("-", "/")
        if "SOL" in record_symbol and _is_external_staked_record(record):
            return record
    return None


def _historical_orphan_summary(orphan_json: Dict[str, Any]) -> Dict[str, Any]:
    orphan_rows = orphan_json.get("orphan_evidence", [])
    open_rows = orphan_json.get("open_positions", [])
    return {
        "verdict": "INFO - historical SOL manual-review rows resolved by authoritative external inventory",
        "external_inventory_resolution": True,
        "historical_orphan_evidence_count": len(orphan_rows) if isinstance(orphan_rows, list) else 0,
        "historical_open_position_rows_count": len(open_rows) if isinstance(open_rows, list) else 0,
        "manual_review_required": False,
        "note": "Historical journal rows remain auditable but are not a current active SOL entry blocker.",
    }


def _contains_sol_blocker(text: str) -> bool:
    t = text.lower()
    return (
        "sol/usd" in t and
        ("dropped after 3" in t or "re-associated" in t or "broker close capability remains unconfirmed" in t)
    )


def _has_unresolved_open_sol(text: str) -> bool:
    t = text.lower()
    return "sol/usd" in t and "open (no confirmed later sell)" in t


def _proceeds_has_direct_facts(text: str) -> bool:
    t = text.lower()
    return "direct broker facts" in t and "sell_proceeds" in t and "complete net" in t


def _proceeds_missing_proceeds(text: str) -> bool:
    t = text.lower()
    return "missing direct sell proceeds" in t or "exit/sell rows missing direct proceeds" in t


def _proceeds_unsafe(text: str) -> bool:
    t = text.lower()
    return "unsafe-to-aggregate" in t or "p/l must remain n/a" in t or "unavailable" in t


def build_aggregator_report(root: Path, telemetry_path: Optional[Path] = None) -> Dict[str, Any]:
    """Core aggregation logic. Returns structured dict (used for both text and JSON)."""
    root = Path(root).resolve()

    proceeds_text = _safe_run_proceeds(root)
    orphan_text = _safe_run_orphan_text(root)
    orphan_json = _safe_run_orphan_json(root)
    price_cov = _safe_price_coverage(telemetry_path)
    stale_blocker = _safe_stale_blocker(root)
    external_sol_record = _external_sol_record(root)

    # --- Detect key signals ---
    sol_blocker_present = _contains_sol_blocker(orphan_text) or _contains_sol_blocker(proceeds_text)
    unresolved_open_sol = _has_unresolved_open_sol(orphan_text)
    staked_external_position = bool(orphan_json.get("staked_external_position") or external_sol_record)
    external_inventory_classification = (
        (external_sol_record or {}).get("external_inventory_classification")
        or orphan_json.get("external_inventory_classification")
    )
    tradable_by_bot = (external_sol_record or {}).get("tradable_by_bot", orphan_json.get("tradable_by_bot"))
    manual_close_allowed = (external_sol_record or {}).get("manual_close_allowed", orphan_json.get("manual_close_allowed"))
    bot_inventory = (external_sol_record or {}).get("bot_inventory", orphan_json.get("bot_inventory"))
    if staked_external_position:
        sol_blocker_present = False
        unresolved_open_sol = False

    has_direct_proceeds = _proceeds_has_direct_facts(proceeds_text)
    missing_proceeds = _proceeds_missing_proceeds(proceeds_text)
    proceeds_unsafe = _proceeds_unsafe(proceeds_text)

    # Orphan structured data
    orphan_error = orphan_json.get("error")
    orphan_blockers = []
    if not orphan_error and not staked_external_position:
        for e in orphan_json.get("external_inventory", []):
            if "SOL" in e.get("symbol", "").upper() and e.get("staked_external_position"):
                orphan_blockers.append("SOL/USD externally staked / unavailable to bot inventory")
        for o in orphan_json.get("orphan_evidence", []):
            orphan_blockers.append(f"{o.get('symbol', '?')}: {o.get('phrase', '')}")
        for op in orphan_json.get("open_positions", []):
            if "SOL" in op.get("symbol", "").upper():
                orphan_blockers.append(f"SOL/USD open without confirmed later sell (qty={op.get('quantity')})")

    # Price coverage summary
    price_evaluable = 0
    if not price_cov.get("error"):
        price_evaluable = price_cov.get("evaluable_telemetry_rows_with_local_prices", 0)

    # --- Synthesize verdict ---
    active_sol_blocker = bool(sol_blocker_present or unresolved_open_sol)
    if external_sol_record:
        active_sol_blocker = False
    if active_sol_blocker or (
        orphan_blockers
        and not staked_external_position
        and any("SOL" in b and not external_sol_record for b in orphan_blockers)
    ):
        verdict = "BLOCKED"
    elif missing_proceeds or proceeds_unsafe or orphan_blockers or price_evaluable == 0:
        verdict = "WARN"
    else:
        verdict = "OK"

    # --- Profit / readout classification (strict rules) ---
    if staked_external_position or active_sol_blocker or (missing_proceeds and not has_direct_proceeds):
        profit_readout = "unsafe_to_aggregate"
    elif has_direct_proceeds:
        profit_readout = "direct"
    elif not missing_proceeds and not proceeds_unsafe:
        profit_readout = "reconstructed"
    else:
        profit_readout = "unavailable"

    # --- Blockers ---
    blockers: List[str] = []
    if staked_external_position:
        blockers.append("SOL/USD externally staked / unavailable to bot inventory; excluded from active entry blockers")
    if active_sol_blocker:
        blockers.append("SOL/USD unresolved / re-associated / broker close capability unconfirmed (dropped after 3 failed attempts evidence present)")
    if missing_proceeds:
        blockers.append("Multiple exit rows lack direct sell_proceeds from broker (P/L cannot be proven)")
    if proceeds_unsafe:
        blockers.append("Fill/proceeds reconciliation reports P/L as unsafe or unavailable")
    if orphan_blockers:
        if staked_external_position:
            blockers.append("Historical SOL manual-review rows resolved by external inventory; not a current entry blocker")
        else:
            blockers.extend(orphan_blockers[:5])
    if price_evaluable == 0:
        blockers.append("Zero evaluable prediction outcome rows have local price coverage")

    if not blockers:
        blockers.append("No critical blockers detected in local data")
    blockers = list(dict.fromkeys(blockers))

    # --- Next action ---
    if staked_external_position:
        next_action = "Keep externally staked SOL excluded from bot-tradable inventory. Continue offline P/L evidence work before any risk increase."
    elif "SOL/USD" in str(blockers):
        next_action = "URGENT: Investigate the SOL/USD position status. Do not aggregate P/L or take further action until direct broker fill + proceeds facts exist."
    elif missing_proceeds or proceeds_unsafe:
        next_action = "Run detailed reconciliation (coinbase_fill_proceeds_reconciliation_report.py) and collect missing direct sell proceeds / per-fill fees before trusting any P/L numbers."
    elif price_evaluable == 0:
        next_action = "Improve local price data coverage (add bars to data/manual_prices/ or ensure dense reference_price telemetry) before relying on outcome scoring."
    else:
        next_action = "Continue normal monitoring. Re-run this aggregator after any material journal or telemetry update."

    proceeds_summary = proceeds_text.split("\n")[:30]
    if staked_external_position:
        legacy_terms = (
            "broker close capability",
            "resolve close",
            "remediate",
            "operational blocker active",
            "sol_blocker",
            "open/re-associated",
        )
        proceeds_summary = [
            line for line in proceeds_summary
            if not any(term in line.lower() for term in legacy_terms)
        ]
    orphan_summary = orphan_json if not orphan_error else {"error": orphan_error}
    if staked_external_position and not orphan_error:
        orphan_summary = _historical_orphan_summary(orphan_json)

    return {
        "verdict": verdict,
        "profit_readout": profit_readout,
        "blockers": blockers,
        "next_action": next_action,
        "sol_blocker_detected": active_sol_blocker,
        "active_sol_entry_blocker_detected": active_sol_blocker,
        "sol_external_inventory_detected": bool(external_sol_record),
        "external_inventory_count": len(_external_inventory_records(root)),
        "staked_external_position": staked_external_position,
        "external_inventory_classification": external_inventory_classification,
        "tradable_by_bot": tradable_by_bot,
        "manual_close_allowed": manual_close_allowed,
        "bot_inventory": bot_inventory,
        "details": {
            "proceeds_summary": proceeds_summary,  # first ~30 lines for context
            "orphan_summary": orphan_summary,
            "price_coverage": price_cov if not price_cov.get("error") else {"error": price_cov.get("error")},
            "stale_blocker": stale_blocker if not stale_blocker.get("error") else {"error": stale_blocker.get("error")},
        },
        "stale_blocker_detected": bool(stale_blocker.get("verdict", "").startswith("STALE")),
        "stale_blocker_reason": stale_blocker.get("blocker_reason"),
        "stale_blocker_age_minutes": stale_blocker.get("blocker_age_minutes"),
        "trading_progress_state": stale_blocker.get("trading_progress_state"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
    }


def format_human_report(data: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=== Coinbase Operator Status Aggregator (P2-014E) ===")
    lines.append("ADVISORY ONLY — 100% read-only local aggregation of existing reports.")
    lines.append(f"Root: {data['root']}")
    lines.append(f"Generated: {data['generated_at']}")
    lines.append("")
    lines.append("--- TOP-LEVEL VERDICT ---")
    lines.append(data["verdict"])
    lines.append("")
    lines.append("--- PROFIT / READOUT STATUS ---")
    lines.append(data["profit_readout"].upper())
    lines.append("")
    lines.append("--- BLOCKERS ---")
    for b in data["blockers"]:
        lines.append(f"  - {b}")
    lines.append("")
    lines.append("--- NEXT RECOMMENDED ACTION ---")
    lines.append(data["next_action"])
    lines.append("")
    if data.get("stale_blocker_detected"):
        lines.append("--- STALE BLOCKER DETECTED (P2-021C2) ---")
        lines.append(f"Reason: {data.get('stale_blocker_reason')}")
        lines.append(f"Age (min): {data.get('stale_blocker_age_minutes')}")
        lines.append(f"Trading state: {data.get('trading_progress_state')}")
        lines.append("")
    lines.append("--- DETAILED SOURCE REPORTS (truncated) ---")
    lines.append("Proceeds reconciliation (first 20 lines):")
    for line in data["details"].get("proceeds_summary", [])[:20]:
        lines.append("  " + str(line)[:120])
    lines.append("")
    lines.append("Open/orphan status: see --json or run coinbase_open_orphan_position_status.py directly")
    lines.append("Price data coverage: see --json or run coinbase_prediction_price_data_status.py directly")
    lines.append("")
    lines.append("Run with --json for full machine-readable output.")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Read-only Coinbase Operator Status Aggregator (P2-014E) — one command view of reconciliation, open positions, and coverage"
    )
    p.add_argument("--root", default=".", help="Repository root (default: .)")
    p.add_argument("--telemetry", default=None, help="Optional path to prediction_telemetry.jsonl")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = p.parse_args(argv)

    root = Path(args.root)
    telemetry = Path(args.telemetry) if args.telemetry else None

    data = build_aggregator_report(root, telemetry)

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(format_human_report(data), end="")

    # Non-zero exit only on real internal error (not on BLOCKED/WARN)
    if data.get("verdict") == "BLOCKED":
        # Still success for the tool itself — the verdict is informational
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
