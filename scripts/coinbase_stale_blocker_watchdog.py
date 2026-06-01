#!/usr/bin/env python3
"""
P2-021C2 — Anti-Stale Manual-Review Blocker Watchdog (read-only, offline only).

Detects when a manual_review_position_open (or similar) entry blocker has become stale.
Surfaces age, counts, severity, and explicit operator action requirements.

This script NEVER:
- Calls any broker API
- Reads .env or secrets
- Places, cancels, closes, or modifies orders
- Mutates state, logs, or runtime files
- Calls append_coinbase_fill_row or writes logs/coinbase_fills.csv
- Auto-unblocks trading or auto-clears positions

It only reads local files for diagnosis and reporting.

It distinguishes:
- True unresolved bot-owned positions (escalate stale state, still block)
- External/staked/non-bot inventory (report as external locked; do not treat as bot inventory or auto-close)
- Stale blocker with no actual open positions (likely state bug)

Usage:
  python3 scripts/coinbase_stale_blocker_watchdog.py --json
  python3 scripts/coinbase_stale_blocker_watchdog.py --stale-threshold-minutes 180
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STALE_THRESHOLD_MINUTES = 180
JOURNAL_FILENAME = "journal_coinbase_crypto.csv"


# --- Minimal safe parsing helpers (self-contained for independence) ---
def key_name(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def normalized(row: Dict[str, str]) -> Dict[str, str]:
    return {key_name(k): (v.strip() if isinstance(v, str) else "") for k, v in row.items() if k is not None}


def first(row: Dict[str, str], keys: List[str]) -> str:
    for key in keys:
        value = row.get(key_name(key), "")
        if value:
            return str(value).strip()
    return ""


def as_time(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def as_bool(value: str) -> Optional[bool]:
    text = str(value or "").strip().lower()
    if text in ("true", "1", "yes", "y"):
        return True
    if text in ("false", "0", "no", "n"):
        return False
    return None


# Journal column groups (consistent with prior safe parsers)
SYMBOL_KEYS = ("symbol", "product_id", "product", "pair")
TIME_KEYS = ("timestamp", "ts", "time", "datetime", "created_at")
REASON_KEYS = ("error", "reason", "message", "notes", "detail", "action", "decision")
ENTRY_TOKENS = ("buy", "entry", "open", "opened", "filled")
MANUAL_REVIEW_PHRASES = (
    "manual_review_position_open",
    "manual review position open",
    "broker_close_capability_unconfirmed",
)


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_heartbeat() -> Dict[str, Any]:
    path = ROOT / "runtime" / "coinbase_heartbeat.json"
    return _safe_load_json(path)


def _load_open_positions() -> Dict[str, Any]:
    path = ROOT / "state" / "coinbase" / "open_positions.json"
    data = _safe_load_json(path)
    # Support both {"positions": {...}} and direct dict forms seen in the wild
    if isinstance(data.get("positions"), dict):
        return data["positions"]
    if isinstance(data, dict) and any(isinstance(v, dict) for v in data.values()):
        # Already symbol-keyed?
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    return {}


def _iter_journal_rows() -> List[Dict[str, str]]:
    path = ROOT / JOURNAL_FILENAME
    if not path.exists():
        return []
    rows: List[Dict[str, str]] = []
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(normalized(row))
    except Exception:
        pass
    return rows


def _is_entry_blocked_manual_review(row: Dict[str, str]) -> bool:
    reason = first(row, REASON_KEYS).lower()
    action = first(row, ["action", "side", "decision", "event"]).lower()
    if "entry_blocked" not in reason and "manual_review_position_open" not in reason:
        return False
    if "manual_review_position_open" in reason:
        return True
    if "entry_blocked" in reason and "manual_review" in reason:
        return True
    return False


def _find_manual_review_blocker_events(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    events = []
    for row in rows:
        if not _is_entry_blocked_manual_review(row):
            continue
        ts = as_time(first(row, TIME_KEYS))
        symbol = first(row, SYMBOL_KEYS).upper()
        reason = first(row, REASON_KEYS)
        if ts:
            events.append({"timestamp": ts, "symbol": symbol, "reason": reason})
    return sorted(events, key=lambda e: e["timestamp"])


def _classify_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    """Return classification for a single open position dict."""
    staked = as_bool(pos.get("staked_external_position")) or as_bool(pos.get("external_staked_position"))
    external_class = first(pos, ["external_inventory_classification", "inventory_classification"]).lower()
    tradable = as_bool(pos.get("tradable_by_bot"))
    bot_owned = as_bool(pos.get("bot_inventory"))
    manual_close = as_bool(pos.get("manual_close_allowed"))

    is_external_staked = bool(
        staked
        or "external" in external_class
        or "staked" in external_class
        or tradable is False
        or bot_owned is False
    )

    user_action = pos.get("user_action_required") is True
    api_ctrl = pos.get("api_controllable")
    exit_eval = pos.get("exit_evaluation_enabled")

    is_manual_review = bool(
        user_action
        or api_ctrl is False
        or exit_eval is False
        or "broker_close" in str(pos.get("manual_review_reason", "")).lower()
        or "unconfirmed" in str(pos.get("manual_review_reason", "")).lower()
    )

    return {
        "is_external_staked": is_external_staked,
        "is_manual_review_unresolved": is_manual_review and not is_external_staked,
        "is_true_bot_owned_unresolved": is_manual_review and not is_external_staked,
    }


def compute_stale_blocker_state(
    heartbeat: Dict[str, Any],
    open_positions: Dict[str, Any],
    journal_rows: List[Dict[str, str]],
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if now is None:
        now = datetime.now(timezone.utc)

    # Heartbeat derived
    last_trade_str = heartbeat.get("last_trade_at") or heartbeat.get("last_exit_at")
    last_trade = as_time(last_trade_str) if last_trade_str else None
    last_loop_str = heartbeat.get("last_loop_time")
    last_loop = as_time(last_loop_str) if last_loop_str else None

    last_trade_age_minutes = None
    if last_trade:
        last_trade_age_minutes = int((now - last_trade).total_seconds() / 60)

    heartbeat_fresh = False
    if last_loop:
        heartbeat_fresh = (now - last_loop).total_seconds() < 10 * 60  # 10 min tolerance

    trades_today = int(heartbeat.get("trades_today") or 0)

    # Open positions analysis
    sol_pos = None
    for sym, pos in open_positions.items():
        if isinstance(pos, dict) and "SOL" in str(sym).upper():
            sol_pos = pos
            break

    sol_classification = _classify_position(sol_pos) if sol_pos else {"is_external_staked": False, "is_manual_review_unresolved": False}

    # Journal blocker events (focus on manual_review_position_open)
    blocker_events = _find_manual_review_blocker_events(journal_rows)
    manual_review_events = [e for e in blocker_events if "manual_review" in e.get("reason", "").lower() or "unconfirmed" in e.get("reason", "").lower()]

    blocker_first = manual_review_events[0]["timestamp"] if manual_review_events else None
    blocker_last = manual_review_events[-1]["timestamp"] if manual_review_events else None

    blocker_age_minutes = None
    if blocker_first:
        blocker_age_minutes = int((now - blocker_first).total_seconds() / 60)

    blocked_count_today = sum(1 for e in manual_review_events if e["timestamp"].date() == now.date())
    blocked_count_window = len(manual_review_events)

    # Decision
    has_stale_manual_review_blocker = False
    if sol_pos and sol_classification.get("is_manual_review_unresolved") and blocker_age_minutes is not None:
        if blocker_age_minutes >= stale_threshold_minutes:
            has_stale_manual_review_blocker = True

    has_stale_state_bug = False
    if len(manual_review_events) > 0 and not any(sol_classification.values()):  # events but no open manual review pos
        # If there are recent manual review blocks but no actual open position with the flag
        has_stale_state_bug = True

    if has_stale_state_bug:
        verdict = "STALE_STATE_BUG_REQUIRES_RESET_REVIEW"
        severity = "HIGH"
        trading_state = "LIVE_BUT_STALE_STATE_INCONSISTENT"
    elif has_stale_manual_review_blocker:
        verdict = "STALE_BLOCKER_REQUIRES_OPERATOR_ACTION"
        severity = "URGENT"
        trading_state = "LIVE_BUT_STALE_BLOCKED"
    elif manual_review_events:
        verdict = "BLOCKED_BUT_NOT_STALE"
        severity = "INFO"
        trading_state = "LIVE_BUT_MANUAL_REVIEW_BLOCKED"
    else:
        verdict = "NO_STALE_BLOCKER_DETECTED"
        severity = "INFO"
        trading_state = "LIVE"

    # External vs bot-owned for the SOL case
    is_external = sol_classification.get("is_external_staked", False)
    is_bot_owned_unresolved = sol_classification.get("is_manual_review_unresolved", False) and not is_external

    return {
        "verdict": verdict,
        "severity": severity,
        "trading_progress_state": trading_state,
        "blocker_reason": "manual_review_position_open" if manual_review_events else None,
        "blocker_first_seen_at": blocker_first.isoformat() if blocker_first else None,
        "blocker_last_seen_at": blocker_last.isoformat() if blocker_last else None,
        "blocker_age_minutes": blocker_age_minutes,
        "stale_threshold_minutes": stale_threshold_minutes,
        "blocked_entry_count_today": blocked_count_today,
        "blocked_entry_count_window": blocked_count_window,
        "last_trade_age_minutes": last_trade_age_minutes,
        "trades_today": trades_today,
        "heartbeat_is_fresh": heartbeat_fresh,
        "bot_process_running": bool(heartbeat.get("status") == "running"),
        "sol_position_classification": {
            "is_external_staked_locked_inventory": is_external,
            "is_true_bot_owned_unresolved": is_bot_owned_unresolved,
            "tradable_by_bot": not is_external,
        },
        "next_required_action": _next_action(verdict, is_external, is_bot_owned_unresolved),
        "generated_at": now.isoformat(),
    }


def _next_action(verdict: str, is_external: bool, is_bot_owned: bool) -> str:
    if is_external:
        return "External/staked inventory detected. Do not attempt auto-close. Exclude from bot inventory and review safe state normalization."
    if verdict == "STALE_BLOCKER_REQUIRES_OPERATOR_ACTION":
        if is_bot_owned:
            return "Run operator status + stale watchdog. Run read-only evidence capture checklist. Obtain explicit human approval. Only then consider read-only broker evidence capture followed by safe state reconciliation."
        return "Investigate state inconsistency. Review open_positions vs journal vs heartbeat."
    if verdict == "STALE_STATE_BUG_REQUIRES_RESET_REVIEW":
        return "Review state/open_positions.json and journal for stale manual_review flags with no actual open position. Manual cleanup of stale flags may be required after review."
    if "MANUAL_REVIEW" in verdict:
        return "Address the underlying manual review position (human action required). Monitor with stale watchdog."
    return "Continue normal operation. Re-run watchdog periodically."


def run_stale_blocker_report(root: Path = ROOT, stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES) -> str:
    """Text report for operator / scripts/coinbase_operator_status.py consumption."""
    heartbeat = _load_heartbeat()
    open_pos = _load_open_positions()
    journal_rows = _iter_journal_rows()

    state = compute_stale_blocker_state(heartbeat, open_pos, journal_rows, stale_threshold_minutes)

    lines = [
        "=== Coinbase Stale Manual-Review Blocker Watchdog (P2-021C2) ===",
        f"Verdict: {state['verdict']}",
        f"Severity: {state['severity']}",
        f"Trading Progress State: {state['trading_progress_state']}",
        "",
        f"Blocker: {state['blocker_reason']}",
        f"First seen: {state['blocker_first_seen_at']}",
        f"Last seen: {state['blocker_last_seen_at']}",
        f"Age (minutes): {state['blocker_age_minutes']} (threshold: {state['stale_threshold_minutes']})",
        "",
        f"Blocked entries today: {state['blocked_entry_count_today']}",
        f"Blocked entries in window: {state['blocked_entry_count_window']}",
        f"Trades today: {state['trades_today']}",
        f"Last trade age (minutes): {state['last_trade_age_minutes']}",
        "",
        f"Heartbeat fresh: {state['heartbeat_is_fresh']}",
        f"Bot process running: {state['bot_process_running']}",
        "",
        "SOL Position Classification:",
        f"  External/staked locked inventory: {state['sol_position_classification']['is_external_staked_locked_inventory']}",
        f"  True bot-owned unresolved: {state['sol_position_classification']['is_true_bot_owned_unresolved']}",
        f"  Tradable by bot: {state['sol_position_classification']['tradable_by_bot']}",
        "",
        f"Next required action: {state['next_required_action']}",
    ]
    return "\n".join(lines)


def run_stale_blocker_report_json(root: Path = ROOT, stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES) -> Dict[str, Any]:
    heartbeat = _load_heartbeat()
    open_pos = _load_open_positions()
    journal_rows = _iter_journal_rows()
    return compute_stale_blocker_state(heartbeat, open_pos, journal_rows, stale_threshold_minutes)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P2-021C2 Anti-Stale Manual-Review Blocker Watchdog (offline, read-only)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--stale-threshold-minutes", type=int, default=DEFAULT_STALE_THRESHOLD_MINUTES, help="Age at which a manual_review blocker is considered stale")
    args = parser.parse_args(argv)

    if args.json:
        report = run_stale_blocker_report_json(stale_threshold_minutes=args.stale_threshold_minutes)
        print(json.dumps(report, indent=2, default=str))
    else:
        text = run_stale_blocker_report(stale_threshold_minutes=args.stale_threshold_minutes)
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
