#!/usr/bin/env python3
"""
ADVISORY ONLY — Read-only local journal inspection for open/orphan Coinbase positions.

This script never calls broker APIs, never reads .env, never makes network calls
(except the separate local_review_gate's explicit git fetch), never places orders,
never writes any files (especially not logs/coinbase_fills.csv), and never calls
append_coinbase_fill_row.

It exists solely to surface operational blockers (especially the known SOL/USD
re-associated / broker-close-unconfirmed / dropped-after-3-failures state) so that
profit readout and close actions remain unsafe until direct broker facts prove
otherwise.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --- Minimal pure parsing helpers (adapted from prior reconciliation report for consistency) ---

def key_name(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")

def normalized(row: Dict[str, str]) -> Dict[str, str]:
    return {key_name(k): (v.strip() if isinstance(v, str) else "") for k, v in row.items() if k is not None}

def first(row: Dict[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key_name(key), "")
        if value:
            return str(value).strip()
    return ""

def as_float(value: str) -> Optional[float]:
    text = str(value or "").strip().replace("$", "").replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        number = float(text)
        if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
            return None
        return number
    except ValueError:
        return None

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

# Column key groups (extended for journal_coinbase_crypto.csv)
SYMBOL_KEYS = ("symbol", "product_id", "product", "pair", "instrument", "ticker")
TIME_KEYS = ("timestamp", "ts", "time", "datetime", "created_at", "filled_at", "entry_time", "exit_time")
ROLE_KEYS = ("side", "action", "event", "event_type", "type", "reason", "order_side", "transaction_type", "decision")
ORDER_KEYS = ("order_id", "coinbase_order_id", "client_order_id", "buy_order_id", "sell_order_id")
QTY_KEYS = ("quantity", "qty", "size", "filled_size", "base_size", "amount", "base_amount")
PRICE_KEYS = ("price", "fill_price", "avg_price", "average_price", "entry_price", "exit_price")
NOTES_KEYS = ("error", "reason", "message", "notes", "warning", "detail", "action", "decision")  # error column holds the gold phrases
STAKED_EXTERNAL_KEYS = ("staked_external_position", "external_staked_position", "staked")
EXTERNAL_CLASSIFICATION_KEYS = ("external_inventory_classification", "inventory_classification")
TRADABLE_BY_BOT_KEYS = ("tradable_by_bot", "bot_tradable")
MANUAL_CLOSE_ALLOWED_KEYS = ("manual_close_allowed", "close_allowed")
BOT_INVENTORY_KEYS = ("bot_inventory", "bot_owned_inventory")

ENTRY_TOKENS = ("buy", "entry", "open", "opened", "filled")
EXIT_TOKENS = ("sell", "exit", "close", "closed", "max_hold", "take_profit", "stop_loss")
DROPPED_PHRASES = (
    "position dropped after 3 failed close attempts",
    "dropped after 3 failed",
)
REASSOCIATED_PHRASES = (
    "broker position re-associated with bot-origin journal evidence",
    "re-associated with bot-origin",
)
UNCERTAIN_CLOSE_PHRASES = (
    "broker close capability remains unconfirmed",
    "close capability remains unconfirmed",
)
EXTERNAL_STAKED_PHRASES = (
    "external_staked_position",
    "externally_locked_inventory",
    "externally staked",
    "staked",
    "bot cannot trade",
    "unavailable to bot",
)

ALLOWED_ROOT_FILES = ("journal_coinbase_crypto.csv", "journal.csv")
ALLOWED_DIRS = ("logs",)
FORBIDDEN_PATH_PARTS = {".env", ".git", "state", "runtime", "launchd", "__pycache__"}

@dataclass(frozen=True)
class PositionEvent:
    source: Path
    row_number: int
    timestamp: Optional[datetime]
    timestamp_raw: str
    symbol: str
    role: str  # ENTRY / EXIT / WARN / OTHER
    order_id: str
    client_order_id: str
    quantity: Optional[float]
    fill_price: Optional[float]
    notes: str
    staked_external_position: Optional[bool]
    external_inventory_classification: str
    tradable_by_bot: Optional[bool]
    manual_close_allowed: Optional[bool]
    bot_inventory: Optional[bool]
    raw_row: Dict[str, str] = field(repr=False)

@dataclass
class OpenPosition:
    symbol: str
    most_recent_entry: Optional[PositionEvent]
    has_later_sell_evidence: bool
    order_id: str
    quantity: Optional[float]
    fill_price: Optional[float]
    timestamp_raw: str
    source: str

@dataclass
class OrphanEvidence:
    symbol: str
    phrase: str
    timestamp_raw: str
    notes: str
    source: str
    row_number: int

@dataclass
class ExternalInventoryEvidence:
    symbol: str
    staked_external_position: bool
    external_inventory_classification: str
    tradable_by_bot: bool
    manual_close_allowed: bool
    bot_inventory: bool
    detection_source: str
    timestamp_raw: str
    notes: str
    source: str
    row_number: int

@dataclass
class CloseCapabilityStatus:
    confirmed_closeable: bool = False
    unconfirmed: bool = False
    failed_close_attempts_seen: int = 0
    manual_review_required: bool = True

@dataclass
class Report:
    verdict: str
    open_positions: List[OpenPosition]
    orphan_evidence: List[OrphanEvidence]
    external_inventory: List[ExternalInventoryEvidence]
    close_capability: CloseCapabilityStatus
    profit_blocker: str
    symbols_with_issues: List[str]
    manual_review_required: bool
    generated_at: str

def classify_role(row: Dict[str, str]) -> str:
    text = (first(row, ROLE_KEYS) + " " + first(row, ["status"])).lower()
    if any(t in text for t in EXIT_TOKENS):
        return "EXIT"
    if any(t in text for t in ENTRY_TOKENS):
        return "ENTRY"
    if "warn" in text or "error" in text or "dropped" in text or "re-associated" in text or "unconfirmed" in text:
        return "WARN"
    return "OTHER"

def candidate_csvs(root: Path) -> List[Path]:
    found: List[Path] = []
    for filename in ALLOWED_ROOT_FILES:
        p = root / filename
        if p.is_file():
            found.append(p)
    for dname in ALLOWED_DIRS:
        d = root / dname
        if d.is_dir():
            for p in sorted(d.rglob("*.csv")):
                if p.is_file() and not any(part in FORBIDDEN_PATH_PARTS for part in p.parts):
                    found.append(p)
    return sorted(set(found))

def read_csv(path: Path) -> Tuple[Tuple[str, ...], List[Dict[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    if not text.strip():
        return tuple(), []
    rows: List[Dict[str, str]] = []
    reader = csv.DictReader(text.splitlines())
    columns = tuple(key_name(c) for c in (reader.fieldnames or []))
    for r in reader:
        rows.append(normalized(r))
    return columns, rows

def to_event(source: Path, row_number: int, row: Dict[str, str]) -> PositionEvent:
    role = classify_role(row)
    symbol = first(row, SYMBOL_KEYS).upper()
    ts_raw = first(row, TIME_KEYS)
    order_id = first(row, ORDER_KEYS)
    client_id = first(row, ["client_order_id"])
    qty = as_float(first(row, QTY_KEYS))
    price = as_float(first(row, PRICE_KEYS + ("fill_price",)))
    notes = first(row, NOTES_KEYS)
    explicit_staked = as_bool(first(row, STAKED_EXTERNAL_KEYS))
    classification = first(row, EXTERNAL_CLASSIFICATION_KEYS)
    tradable = as_bool(first(row, TRADABLE_BY_BOT_KEYS))
    manual_close = as_bool(first(row, MANUAL_CLOSE_ALLOWED_KEYS))
    bot_inventory = as_bool(first(row, BOT_INVENTORY_KEYS))
    return PositionEvent(
        source=source,
        row_number=row_number,
        timestamp=as_time(ts_raw),
        timestamp_raw=ts_raw,
        symbol=symbol,
        role=role,
        order_id=order_id,
        client_order_id=client_id,
        quantity=qty,
        fill_price=price,
        notes=notes,
        staked_external_position=explicit_staked,
        external_inventory_classification=classification,
        tradable_by_bot=tradable,
        manual_close_allowed=manual_close,
        bot_inventory=bot_inventory,
        raw_row=row,
    )

def scan_events(root: Path) -> List[PositionEvent]:
    events: List[PositionEvent] = []
    for p in candidate_csvs(root):
        _, raw_rows = read_csv(p)
        for i, r in enumerate(raw_rows, start=2):
            ev = to_event(p, i, r)
            if ev.symbol or ev.notes or ev.order_id:
                events.append(ev)
    # sort by time (oldest first) for later matching
    events.sort(key=lambda e: e.timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return events

def detect_orphan_evidence(events: Sequence[PositionEvent]) -> List[OrphanEvidence]:
    orphans: List[OrphanEvidence] = []
    for ev in events:
        notes_lower = (ev.notes or "").lower()
        for phrase in DROPPED_PHRASES + REASSOCIATED_PHRASES + UNCERTAIN_CLOSE_PHRASES:
            if phrase in notes_lower:
                orphans.append(OrphanEvidence(
                    symbol=ev.symbol or "UNKNOWN",
                    phrase=phrase,
                    timestamp_raw=ev.timestamp_raw,
                    notes=ev.notes,
                    source=str(ev.source),
                    row_number=ev.row_number,
                ))
    return orphans

def detect_external_inventory(events: Sequence[PositionEvent]) -> List[ExternalInventoryEvidence]:
    """Detect inventory that is explicitly unavailable to the bot.

    Structured columns are authoritative. Phrase detection is a secondary
    backward-compatible fallback for older local journals/reports.
    """
    evidence: List[ExternalInventoryEvidence] = []
    seen = set()
    for ev in events:
        text = " ".join([ev.notes or "", ev.external_inventory_classification or ""]).lower()
        explicit = (
            ev.staked_external_position is True or
            (ev.external_inventory_classification or "").lower() in (
                "external_staked_position",
                "externally_locked_inventory",
            ) or
            ev.tradable_by_bot is False or
            ev.manual_close_allowed is False or
            ev.bot_inventory is False
        )
        phrase_fallback = (
            "SOL" in (ev.symbol or "").upper() and
            any(phrase in text for phrase in EXTERNAL_STAKED_PHRASES)
        )
        if not (explicit or phrase_fallback):
            continue
        classification = (ev.external_inventory_classification or "external_staked_position").lower()
        if classification not in ("external_staked_position", "externally_locked_inventory"):
            classification = "external_staked_position"
        item = ExternalInventoryEvidence(
            symbol=ev.symbol or "UNKNOWN",
            staked_external_position=True,
            external_inventory_classification=classification,
            tradable_by_bot=False if ev.tradable_by_bot is None else ev.tradable_by_bot,
            manual_close_allowed=False if ev.manual_close_allowed is None else ev.manual_close_allowed,
            bot_inventory=False if ev.bot_inventory is None else ev.bot_inventory,
            detection_source="structured" if explicit else "phrase_fallback",
            timestamp_raw=ev.timestamp_raw,
            notes=ev.notes,
            source=str(ev.source),
            row_number=ev.row_number,
        )
        key = (item.symbol, item.external_inventory_classification, item.source, item.row_number)
        if key not in seen:
            seen.add(key)
            evidence.append(item)
    return evidence

def find_open_positions(events: Sequence[PositionEvent]) -> List[OpenPosition]:
    """Very simple heuristic: for each ENTRY, look for any later EXIT on same symbol.
    If none found, treat as open/unresolved (conservative for operator).
    """
    opens: List[OpenPosition] = []
    by_symbol: Dict[str, List[PositionEvent]] = {}
    for ev in events:
        if ev.symbol:
            by_symbol.setdefault(ev.symbol, []).append(ev)

    for symbol, sym_events in by_symbol.items():
        entries = [e for e in sym_events if e.role == "ENTRY"]
        exits = [e for e in sym_events if e.role == "EXIT"]
        for entry in entries:
            has_later_sell = False
            for ex in exits:
                if ex.timestamp and entry.timestamp and ex.timestamp > entry.timestamp:
                    # loose match on symbol (already filtered) + qty similarity if available
                    if entry.quantity and ex.quantity and abs(entry.quantity - ex.quantity) < 1e-6:
                        has_later_sell = True
                        break
                    if not entry.quantity or not ex.quantity:
                        has_later_sell = True  # conservative
                        break
            if not has_later_sell:
                opens.append(OpenPosition(
                    symbol=symbol,
                    most_recent_entry=entry,
                    has_later_sell_evidence=False,
                    order_id=entry.order_id or entry.client_order_id,
                    quantity=entry.quantity,
                    fill_price=entry.fill_price,
                    timestamp_raw=entry.timestamp_raw,
                    source=str(entry.source),
                ))
    return opens

def compute_close_capability(
    orphans: Sequence[OrphanEvidence],
    opens: Sequence[OpenPosition],
    external_inventory: Sequence[ExternalInventoryEvidence] = (),
) -> CloseCapabilityStatus:
    if external_inventory and not opens and not orphans:
        return CloseCapabilityStatus(
            confirmed_closeable=False,
            unconfirmed=False,
            failed_close_attempts_seen=0,
            manual_review_required=False,
        )
    status = CloseCapabilityStatus()
    for o in orphans:
        n = o.notes.lower()
        if "dropped after 3" in n or "3 failed" in n:
            status.failed_close_attempts_seen = 3
            status.unconfirmed = True
        if "re-associated" in n or "bot-origin" in n:
            status.unconfirmed = True
        if "unconfirmed" in n or "close capability" in n:
            status.unconfirmed = True
    if opens:
        status.manual_review_required = True
        status.unconfirmed = True
    if status.unconfirmed or status.failed_close_attempts_seen > 0:
        status.confirmed_closeable = False
        status.manual_review_required = True
    else:
        status.confirmed_closeable = len(opens) == 0
        status.manual_review_required = len(opens) > 0
    return status

def build_verdict(
    opens: Sequence[OpenPosition],
    orphans: Sequence[OrphanEvidence],
    status: CloseCapabilityStatus,
    external_inventory: Sequence[ExternalInventoryEvidence] = (),
) -> str:
    if any("SOL" in e.symbol.upper() and e.staked_external_position for e in external_inventory):
        return "BLOCKED — SOL/USD externally staked / unavailable to bot inventory"
    if orphans or any("SOL" in o.symbol for o in opens):
        return "BLOCKED — unresolved SOL/USD broker close capability / dropped position evidence present"
    if opens:
        return "WARN — open/unresolved positions detected; manual review required before any close or P/L aggregation"
    if status.unconfirmed:
        return "WARN — broker close capability unconfirmed on historical positions"
    return "PASS — no open or orphan position blockers detected in local journals"

def build_profit_blocker(
    opens: Sequence[OpenPosition],
    orphans: Sequence[OrphanEvidence],
    external_inventory: Sequence[ExternalInventoryEvidence] = (),
) -> str:
    if any("SOL" in e.symbol.upper() and e.staked_external_position for e in external_inventory):
        return ("Realized P/L remains unsafe-to-aggregate. SOL/USD is externally staked "
                "and unavailable to bot inventory, so the bot must not trade it or infer "
                "realized P/L from it.")
    if opens or orphans:
        return ("Realized P/L and outcome scoring remain unsafe-to-aggregate. "
                "Open/orphan positions (especially SOL/USD re-associated with unconfirmed broker close) "
                "lack direct sell proceeds + per-fill fee evidence from broker. "
                "Do not infer any position is closed unless an explicit later sell/exit/fill row with proceeds exists after the entry.")
    return "No open/orphan blockers detected in local data; P/L aggregation still requires direct broker fill/proceeds reconciliation (see P2-014B report)."

def run_report(root: Path) -> str:
    root = root.resolve()
    events = scan_events(root)
    external_inventory = detect_external_inventory(events)
    orphans = detect_orphan_evidence(events)
    opens = find_open_positions(events)
    close_status = compute_close_capability(orphans, opens, external_inventory)
    verdict = build_verdict(opens, orphans, close_status, external_inventory)
    blocker = build_profit_blocker(opens, orphans, external_inventory)
    symbols = sorted(set(o.symbol for o in opens) | set(o.symbol for o in orphans) | set(e.symbol for e in external_inventory))

    lines: List[str] = []
    lines.append("=== Coinbase Open / Orphan Position Status Report (read-only, local journals only) ===")
    lines.append("ADVISORY ONLY — No broker calls, no writes, no network (except gate git fetch).")
    lines.append(f"Root: {root}")
    lines.append("")

    lines.append("--- 1. Verdict ---")
    lines.append(verdict)
    lines.append("")

    lines.append("--- 2. Current / open position evidence ---")
    if opens:
        for op in opens:
            lines.append(f"  SYMBOL={op.symbol} | open (no confirmed later sell) | "
                         f"order_id={op.order_id or 'n/a'} | qty={op.quantity} | fill_price={op.fill_price} | "
                         f"ts={op.timestamp_raw} | source={op.source}:{op.most_recent_entry.row_number if op.most_recent_entry else '?'}")
    else:
        lines.append("  No open/unresolved buys without later sell evidence found.")
    lines.append("")

    lines.append("--- 3. Dropped / re-associated / orphan evidence ---")
    if orphans:
        for o in orphans:
            lines.append(f"  {o.symbol} | {o.phrase} | ts={o.timestamp_raw} | {o.source}:{o.row_number}")
            if o.notes:
                lines.append(f"    full: {o.notes[:200]}")
    else:
        lines.append("  No dropped/re-associated/unconfirmed phrases detected.")
    lines.append("")

    lines.append("--- 4. Close capability status ---")
    if external_inventory:
        lines.append("  staked_inventory_note: do not close/remediate while staked")
    lines.append(f"  confirmed_closeable: {close_status.confirmed_closeable}")
    lines.append(f"  unconfirmed: {close_status.unconfirmed}")
    lines.append(f"  failed_close_attempts_seen: {close_status.failed_close_attempts_seen}")
    lines.append(f"  manual_review_required: {close_status.manual_review_required}")
    lines.append("")

    lines.append("--- 5. External / locked inventory ---")
    if external_inventory:
        for e in external_inventory:
            lines.append(f"  SYMBOL={e.symbol} | externally staked / unavailable to bot | "
                         f"classification={e.external_inventory_classification} | "
                         f"tradable_by_bot={e.tradable_by_bot} | "
                         f"manual_close_allowed={e.manual_close_allowed} | "
                         f"bot_inventory={e.bot_inventory} | source={e.source}:{e.row_number}")
    else:
        lines.append("  No external locked inventory evidence detected.")
    lines.append("")

    lines.append("--- 6. Profit / readout blocker ---")
    lines.append(blocker)
    lines.append("")

    lines.append("--- 7. Machine-readable (use --json) ---")
    lines.append("Run with --json for structured output suitable for dashboards.")
    lines.append("")

    lines.append("Generated at: " + datetime.now(timezone.utc).isoformat())
    return "\n".join(lines) + "\n"

def run_report_json(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    events = scan_events(root)
    external_inventory = detect_external_inventory(events)
    orphans = detect_orphan_evidence(events)
    opens = find_open_positions(events)
    close_status = compute_close_capability(orphans, opens, external_inventory)
    verdict = build_verdict(opens, orphans, close_status, external_inventory)
    blocker = build_profit_blocker(opens, orphans, external_inventory)
    symbols = sorted(set(o.symbol for o in opens) | set(o.symbol for o in orphans) | set(e.symbol for e in external_inventory))
    sol_external = any("SOL" in e.symbol.upper() and e.staked_external_position for e in external_inventory)

    note = "Read-only local analysis only. Profit and close actions remain unsafe until direct broker facts confirm resolution."
    if sol_external:
        note = "Read-only local analysis only. Staked SOL is unavailable to bot inventory; do not close/remediate while staked."

    return {
        "verdict": verdict,
        "open_positions": [asdict(o) for o in opens],
        "orphan_evidence": [asdict(o) for o in orphans],
        "external_inventory": [asdict(e) for e in external_inventory],
        "staked_external_position": sol_external,
        "external_inventory_classification": "external_staked_position" if sol_external else None,
        "tradable_by_bot": False if sol_external else None,
        "manual_close_allowed": False if sol_external else None,
        "bot_inventory": False if sol_external else None,
        "close_capability": asdict(close_status),
        "profit_blocker": blocker,
        "symbols_with_issues": symbols,
        "manual_review_required": close_status.manual_review_required or bool(opens) or bool(orphans),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "note": note,
    }

def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Read-only local open/orphan Coinbase position status (P2-014D)")
    p.add_argument("--root", default=".", help="Repository root to scan")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of human text")
    args = p.parse_args(argv)

    root = Path(args.root)
    if args.json:
        print(json.dumps(run_report_json(root), indent=2, default=str))
    else:
        print(run_report(root), end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
