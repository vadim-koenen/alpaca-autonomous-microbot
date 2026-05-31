#!/usr/bin/env python3
"""
ADVISORY ONLY — Coinbase fill/proceeds reconciliation report.

Read-only local CSV inspection only. This script does not call broker APIs,
does not read .env, does not place orders, does not modify config/state/runtime,
and does not affect live trading behavior.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ALLOWED_ROOT_FILES = ("journal_coinbase_crypto.csv",)
ALLOWED_DIRS = ("logs", "reports")
FORBIDDEN_PATH_PARTS = {".env", ".git", "state", "runtime", "launchd", "__pycache__"}

SYMBOL_KEYS = ("symbol", "product_id", "product", "pair", "instrument", "ticker")
TIME_KEYS = ("timestamp", "ts", "time", "datetime", "created_at", "filled_at", "entry_time", "exit_time")
ROLE_KEYS = ("side", "action", "event", "event_type", "type", "reason", "order_side", "transaction_type")
PAIR_KEYS = ("trade_id", "cycle_id", "position_id", "entry_id", "client_order_id", "order_id")
ORDER_KEYS = ("order_id", "coinbase_order_id", "client_order_id", "buy_order_id", "sell_order_id")
QTY_KEYS = ("quantity", "qty", "size", "filled_size", "base_size", "amount", "base_amount")
PRICE_KEYS = ("price", "fill_price", "avg_price", "average_price", "entry_price", "exit_price")
BUY_VALUE_KEYS = ("buy_cost", "cost", "entry_notional", "notional", "quote_amount", "quote_size", "filled_value", "value", "amount_usd", "usd_value")
SELL_VALUE_KEYS = ("sell_proceeds", "proceeds", "gross_proceeds", "exit_proceeds", "quote_amount", "quote_size", "filled_value", "value", "amount_usd", "usd_value", "proceeds_usd")
FEE_KEYS = ("fee", "fees", "commission", "fee_usd", "fees_usd", "total_fee")
PNL_KEYS = ("pnl", "realized_pnl", "profit_loss", "net_pnl", "gross_pnl")
REASON_KEYS = ("reason", "error", "message", "notes", "warning", "detail", "action", "decision")

ENTRY = "entry/buy"
EXIT = "exit/sell"
SKIP = "skip"
OTHER = "other"


@dataclass(frozen=True)
class EvidenceRow:
    source: Path
    row_number: int
    role: str
    symbol: str
    timestamp_raw: str
    timestamp: Optional[datetime]
    pair_id: str
    order_id: str
    quantity: Optional[float]
    price: Optional[float]
    buy_cost: Optional[float]
    sell_proceeds: Optional[float]
    fee: Optional[float]
    pnl: Optional[float]
    missing_fields: Tuple[str, ...]
    notes: str = ""  # free-text reason/error/warning for blocker detection (e.g. "broker close capability remains unconfirmed")


@dataclass(frozen=True)
class FileProfile:
    source: Path
    row_count: int
    columns: Tuple[str, ...]
    entries: int
    exits: int
    exits_with_proceeds: int
    rows_with_fees: int
    rows_with_order_ids: int
    rows_with_pnl: int


@dataclass(frozen=True)
class PairResult:
    method: str
    entry: EvidenceRow
    exit: EvidenceRow
    gross_pnl: Optional[float]
    net_pnl: Optional[float]
    verdict: str


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
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


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
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def classify(row: Dict[str, str]) -> str:
    text = first(row, ROLE_KEYS).lower()

    if "skip" in text or "reject" in text:
        return SKIP

    exit_tokens = ("sell", "exit", "close", "closed", "max_hold", "take_profit", "stop_loss", "stop loss")
    entry_tokens = ("buy", "entry", "open", "opened")

    if any(token in text for token in exit_tokens):
        return EXIT
    if any(token in text for token in entry_tokens):
        return ENTRY
    return OTHER


def candidate_csvs(root: Path) -> List[Path]:
    found: List[Path] = []

    for filename in ALLOWED_ROOT_FILES:
        path = root / filename
        if path.is_file():
            found.append(path)

    for dirname in ALLOWED_DIRS:
        directory = root / dirname
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.csv")):
            if path.is_file() and not any(part in FORBIDDEN_PATH_PARTS for part in path.parts):
                found.append(path)

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
    columns = tuple(key_name(column) for column in (reader.fieldnames or []))
    for row in reader:
        rows.append(normalized(row))
    return columns, rows


def evidence_row(source: Path, row_number: int, row: Dict[str, str]) -> EvidenceRow:
    role = classify(row)
    symbol = first(row, SYMBOL_KEYS)
    timestamp_raw = first(row, TIME_KEYS)
    pair_id = first(row, PAIR_KEYS)
    order_id = first(row, ORDER_KEYS)
    quantity = as_float(first(row, QTY_KEYS))
    price = as_float(first(row, PRICE_KEYS))
    buy_cost = as_float(first(row, BUY_VALUE_KEYS)) if role == ENTRY else None
    sell_proceeds = as_float(first(row, SELL_VALUE_KEYS)) if role == EXIT else None
    fee = as_float(first(row, FEE_KEYS))
    pnl = as_float(first(row, PNL_KEYS))
    notes = first(row, REASON_KEYS)

    missing: List[str] = []
    if role in (ENTRY, EXIT):
        if not symbol:
            missing.append("symbol/product_id")
        if not timestamp_raw:
            missing.append("timestamp")
        if not order_id:
            missing.append("order_id")
        if quantity is None:
            missing.append("quantity/size")
        if price is None:
            missing.append("fill_price")
        if fee is None:
            missing.append("fee")
    if role == ENTRY and buy_cost is None:
        missing.append("buy_cost/notional")
    if role == EXIT and sell_proceeds is None:
        missing.append("sell_proceeds")

    return EvidenceRow(
        source=source,
        row_number=row_number,
        role=role,
        symbol=symbol,
        timestamp_raw=timestamp_raw,
        timestamp=as_time(timestamp_raw),
        pair_id=pair_id,
        order_id=order_id,
        quantity=quantity,
        price=price,
        buy_cost=buy_cost,
        sell_proceeds=sell_proceeds,
        fee=fee,
        pnl=pnl,
        missing_fields=tuple(missing),
        notes=notes,
    )


def profile(source: Path, columns: Tuple[str, ...], rows: Sequence[EvidenceRow]) -> FileProfile:
    return FileProfile(
        source=source,
        row_count=len(rows),
        columns=columns,
        entries=sum(1 for row in rows if row.role == ENTRY),
        exits=sum(1 for row in rows if row.role == EXIT),
        exits_with_proceeds=sum(1 for row in rows if row.role == EXIT and row.sell_proceeds is not None),
        rows_with_fees=sum(1 for row in rows if row.fee is not None),
        rows_with_order_ids=sum(1 for row in rows if row.order_id),
        rows_with_pnl=sum(1 for row in rows if row.pnl is not None),
    )


def scan(root: Path) -> Tuple[List[FileProfile], List[EvidenceRow]]:
    profiles: List[FileProfile] = []
    evidence: List[EvidenceRow] = []

    for source in candidate_csvs(root):
        columns, raw_rows = read_csv(source)
        rows = [evidence_row(source, index + 2, row) for index, row in enumerate(raw_rows)]
        profiles.append(profile(source, columns, rows))
        evidence.extend(rows)

    return profiles, evidence


def row_key(row: EvidenceRow) -> Tuple[str, datetime, int]:
    fallback = datetime.max.replace(tzinfo=timezone.utc)
    return row.symbol, row.timestamp or fallback, row.row_number


def fee_total(entry_fee: Optional[float], exit_fee: Optional[float]) -> Optional[float]:
    fees = [abs(value) for value in (entry_fee, exit_fee) if value is not None]
    if not fees:
        return None
    return sum(fees)


def make_pair(method: str, entry: EvidenceRow, exit_row: EvidenceRow) -> PairResult:
    gross = None
    net = None

    if entry.buy_cost is not None and exit_row.sell_proceeds is not None:
        gross = exit_row.sell_proceeds - entry.buy_cost
        fees = fee_total(entry.fee, exit_row.fee)
        if fees is None:
            verdict = "complete_gross_fee_missing"
        else:
            net = gross - fees
            verdict = "complete_gross_and_net"
    else:
        verdict = "incomplete_missing_buy_cost_or_sell_proceeds"

    return PairResult(method, entry, exit_row, gross, net, verdict)


def pair_rows(evidence: Sequence[EvidenceRow]) -> List[PairResult]:
    entries = [row for row in evidence if row.role == ENTRY]
    exits = [row for row in evidence if row.role == EXIT]
    pairs: List[PairResult] = []
    used_entries = set()
    used_exits = set()

    by_pair_id: Dict[str, List[EvidenceRow]] = {}
    for entry in entries:
        if entry.pair_id:
            by_pair_id.setdefault(entry.pair_id, []).append(entry)

    for exit_row in exits:
        if not exit_row.pair_id:
            continue
        for entry in by_pair_id.get(exit_row.pair_id, []):
            entry_key = (entry.source, entry.row_number)
            exit_key = (exit_row.source, exit_row.row_number)
            if entry_key not in used_entries and exit_key not in used_exits:
                pairs.append(make_pair("exact_pairing_id", entry, exit_row))
                used_entries.add(entry_key)
                used_exits.add(exit_key)
                break

    remaining_entries = [row for row in sorted(entries, key=row_key) if (row.source, row.row_number) not in used_entries]
    remaining_exits = [row for row in sorted(exits, key=row_key) if (row.source, row.row_number) not in used_exits]

    for exit_row in remaining_exits:
        exit_key = (exit_row.source, exit_row.row_number)
        for entry in remaining_entries:
            entry_key = (entry.source, entry.row_number)
            if entry_key in used_entries:
                continue
            if entry.symbol and exit_row.symbol and entry.symbol != exit_row.symbol:
                continue
            if entry.timestamp and exit_row.timestamp and entry.timestamp > exit_row.timestamp:
                continue
            pairs.append(make_pair("symbol_time_fifo", entry, exit_row))
            used_entries.add(entry_key)
            used_exits.add(exit_key)
            break

    return pairs


def detect_direct_facts(evidence: Sequence[EvidenceRow]) -> Dict[str, int]:
    """Count rows that contain direct broker facts (vs derived/missing)."""
    return {
        "rows_with_order_id": sum(1 for r in evidence if r.order_id),
        "rows_with_direct_proceeds": sum(1 for r in evidence if r.sell_proceeds is not None),
        "rows_with_direct_fees": sum(1 for r in evidence if r.fee is not None),
        "rows_with_buy_cost": sum(1 for r in evidence if r.buy_cost is not None),
        "rows_with_pair_id": sum(1 for r in evidence if r.pair_id),
    }


def detect_unsafe_reasons(evidence: Sequence[EvidenceRow], pairs: Sequence[PairResult]) -> List[str]:
    """Return human-readable unsafe-to-aggregate reasons."""
    reasons: List[str] = []
    exit_rows = [r for r in evidence if r.role == EXIT]
    missing_proceeds_exits = [r for r in exit_rows if r.sell_proceeds is None]
    if missing_proceeds_exits:
        reasons.append(f"{len(missing_proceeds_exits)} exit/sell row(s) lack direct sell_proceeds from broker fill (cannot compute realized P/L without immutable broker fact)")
    missing_fees = [r for r in evidence if r.role in (ENTRY, EXIT) and r.fee is None]
    if missing_fees:
        reasons.append(f"{len(missing_fees)} entry/exit row(s) lack explicit fee fields (net P/L unsafe; gross may be locally derivable)")
    missing_order = [r for r in evidence if r.role in (ENTRY, EXIT) and not r.order_id]
    if missing_order:
        reasons.append(f"{len(missing_order)} entry/exit row(s) lack stable order_id / client_order_id (cannot tie to direct broker fill event)")
    missing_pair = [r for r in evidence if r.role in (ENTRY, EXIT) and not r.pair_id]
    if missing_pair:
        reasons.append(f"{len(missing_pair)} entry/exit row(s) lack stable pair/trade/cycle id (pairing falls back to symbol+time FIFO, which is locally derived)")
    incomplete_pairs = [p for p in pairs if p.gross_pnl is None]
    if incomplete_pairs:
        reasons.append(f"{len(incomplete_pairs)} paired cycle(s) missing buy_cost or sell_proceeds (P/L unavailable)")
    # Journal intent warning (always true for this data source)
    reasons.append("Journal EXIT/PLACED rows record bot intent + local estimates; they are NOT immutable broker fill facts with guaranteed proceeds/fees. Direct broker facts must come from order status + fills responses.")
    return reasons


def detect_sol_blocker(evidence: Sequence[EvidenceRow]) -> List[str]:
    """Surface SOL/USD open/re-associated + broker close unconfirmed as operational blocker."""
    blockers: List[str] = []
    sol_rows = [r for r in evidence if (r.symbol or "").upper().startswith("SOL/")]
    unconfirmed_texts = []
    for r in sol_rows:
        text = (r.notes or "").lower()
        if "unconfirmed" in text or "broker close capability" in text or "dropped after 3" in text or "re-associated" in text:
            unconfirmed_texts.append(r.notes or "broker close capability remains unconfirmed")
    if unconfirmed_texts:
        unique = list(dict.fromkeys(unconfirmed_texts))  # dedup preserve order
        blockers.append(f"SOL/USD operational blocker active: {'; '.join(unique)} — do not treat position as closed; no explicit matching sell/proceeds/fill fact confirms broker close.")
    # Also flag unmatched open SOL buys (no paired exit with proceeds)
    open_sol_buys = [r for r in evidence if r.role == ENTRY and (r.symbol or "").upper().startswith("SOL/")]
    # (pairing happens later; for simplicity here we note presence of recent SOL entries)
    if open_sol_buys and not any(r for r in evidence if r.role == EXIT and (r.symbol or "").upper().startswith("SOL/") and r.sell_proceeds is not None):
        blockers.append("SOL/USD open/re-associated bot-origin position evidence present in journal (no confirmed direct sell proceeds on matching exit).")
    return blockers


def classify_pnl_type(pairs: Sequence[PairResult]) -> str:
    """Return clear label for what kind of P/L (if any) is available."""
    if any(p.net_pnl is not None for p in pairs):
        return "net P/L locally reconstructed from complete direct broker facts (buy_cost + sell_proceeds + fees)"
    if any(p.gross_pnl is not None for p in pairs):
        return "gross P/L locally derived from direct buy_cost + sell_proceeds (fees missing or incomplete; net unsafe)"
    return "unavailable (no paired cycle has both direct buy_cost and direct sell_proceeds)"


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def money(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.6f}"


def render(root: Path, profiles: Sequence[FileProfile], evidence: Sequence[EvidenceRow], pairs: Sequence[PairResult]) -> str:
    lines: List[str] = []
    lines.append("=== Coinbase Fill / Proceeds Reconciliation Report ===")
    lines.append("ADVISORY ONLY / READ ONLY / LOCAL CSV INSPECTION ONLY")
    lines.append(f"Root: {root}")
    lines.append("")

    if not profiles:
        lines.append("No candidate local CSV files found in journal_coinbase_crypto.csv, logs/, or reports/.")
        lines.append("Verdict: P/L reconstruction is unavailable until fill/proceeds data is logged locally.")
        return "\n".join(lines) + "\n"

    # === NEW: Concise Verdict near top (P2-014B) ===
    facts = detect_direct_facts(evidence)
    unsafe_reasons = detect_unsafe_reasons(evidence, pairs)
    sol_blockers = detect_sol_blocker(evidence)
    pnl_type = classify_pnl_type(pairs)
    complete_gross = [pair for pair in pairs if pair.gross_pnl is not None]
    complete_net = [pair for pair in pairs if pair.net_pnl is not None]

    lines.append("--- Reconciliation Verdict (P2-014B) ---")
    lines.append(f"Direct broker facts coverage: order_id={facts['rows_with_order_id']}, direct_proceeds={facts['rows_with_direct_proceeds']}, direct_fees={facts['rows_with_direct_fees']}, buy_cost={facts['rows_with_buy_cost']}, pair_id={facts['rows_with_pair_id']}")
    lines.append(f"Realized P/L status: {pnl_type}")
    if complete_net:
        lines.append(f"Net pairs reconstructable from direct facts: {len(complete_net)} (locally reconstructed gross+net using pairing methods below)")
    elif complete_gross:
        lines.append(f"Gross pairs only (locally derived from direct proceeds; net unsafe due to missing fees): {len(complete_gross)}")
    else:
        lines.append("Realized P&L unavailable: no cycle has both direct buy_cost and direct sell_proceeds from broker.")
    if sol_blockers:
        for b in sol_blockers:
            lines.append(f"BLOCKER: {b}")
    lines.append("Profit readout remains unsafe-to-aggregate until direct fill/proceeds/fees reconciliation proven from broker responses.")
    lines.append("")

    # === NEW: Direct fact coverage (P2-014B) ===
    lines.append("--- Direct broker facts available from local rows ---")
    lines.append(f"order_id / client_order_id present: {facts['rows_with_order_id']} rows (direct broker fact — ties to immutable exchange event)")
    lines.append(f"filled_size / quantity present: {sum(1 for r in evidence if r.quantity is not None)} rows")
    lines.append(f"fill_price / average_price present: {sum(1 for r in evidence if r.price is not None)} rows")
    lines.append(f"explicit fee fields present: {facts['rows_with_direct_fees']} rows (direct broker fact)")
    lines.append(f"explicit sell_proceeds / filled_value / proceeds present: {facts['rows_with_direct_proceeds']} rows (direct broker fact — actual exit credit)")
    lines.append(f"buy_cost / entry_notional present on entries: {facts['rows_with_buy_cost']} rows (direct or locally captured cost)")
    lines.append(f"existing pnl fields (journal-derived): {sum(1 for r in evidence if r.pnl is not None)} rows (treated as locally_derived unless corroborated by direct proceeds+fees)")
    lines.append("")

    # === NEW: Unsafe-to-aggregate reasons (P2-014B) ===
    lines.append("--- Unsafe-to-aggregate reasons ---")
    for reason in unsafe_reasons:
        lines.append(f"- {reason}")
    # legacy missing proceeds list for compat
    exit_rows = [row for row in evidence if row.role == EXIT]
    missing_proceeds = [row for row in exit_rows if row.sell_proceeds is None]
    if missing_proceeds:
        lines.append(f"Exit/sell rows missing direct proceeds: {len(missing_proceeds)}")
        for row in missing_proceeds[:10]:
            lines.append(
                f"  MISSING_PROCEEDS {relative(row.source, root)}:{row.row_number} "
                f"symbol={row.symbol or 'n/a'} time={row.timestamp_raw or 'n/a'} order_id={row.order_id or 'n/a'}"
            )
        if len(missing_proceeds) > 10:
            lines.append(f"  ... {len(missing_proceeds) - 10} additional omitted")
    lines.append("")

    # === NEW: Open/unresolved position evidence (P2-014B) — especially SOL blocker ===
    lines.append("--- Open/unresolved position evidence ---")
    if sol_blockers:
        for b in sol_blockers:
            lines.append(f"SOL_BLOCKER: {b}")
    open_entries = [r for r in evidence if r.role == ENTRY and not any(p.entry is r for p in pairs)]
    if open_entries:
        lines.append(f"Unmatched open buy entries (no paired exit with proceeds): {len(open_entries)}")
        for r in open_entries[:5]:
            lines.append(f"  OPEN {relative(r.source, root)}:{r.row_number} symbol={r.symbol or 'n/a'} order_id={r.order_id or 'n/a'} (P/L n/a; no direct sell proceeds fact)")
    # Also surface any SOL WARN rows with unconfirmed text even if OTHER role
    for r in evidence:
        if (r.symbol or "").upper().startswith("SOL/") and r.notes and ("unconfirmed" in r.notes.lower() or "dropped after 3" in r.notes.lower()):
            lines.append(f"SOL_UNRESOLVED_NOTE {relative(r.source, root)}:{r.row_number}: {r.notes}")
    if not sol_blockers and not open_entries:
        lines.append("No open/unresolved SOL or unmatched entries detected in this scan.")
    lines.append("")

    # === Files + Field coverage (kept for backward compat + detail) ===
    lines.append("--- Files inspected ---")
    for item in profiles:
        lines.append(
            f"{relative(item.source, root)} | rows={item.row_count} | entries={item.entries} | "
            f"exits={item.exits} | exits_with_proceeds={item.exits_with_proceeds} | "
            f"fee_rows={item.rows_with_fees} | order_id_rows={item.rows_with_order_ids} | pnl_rows={item.rows_with_pnl}"
        )
    lines.append("")

    lines.append("--- Field coverage ---")
    lines.append(f"buy_rows: {sum(1 for row in evidence if row.role == ENTRY)}")
    lines.append(f"sell_or_exit_rows: {sum(1 for row in evidence if row.role == EXIT)}")
    lines.append(f"sell_or_exit_rows_with_proceeds: {sum(1 for row in evidence if row.role == EXIT and row.sell_proceeds is not None)}")
    lines.append(f"rows_with_fees: {sum(1 for row in evidence if row.fee is not None)}")
    lines.append(f"rows_with_order_ids: {sum(1 for row in evidence if row.order_id)}")
    lines.append(f"rows_with_pairing_ids: {sum(1 for row in evidence if row.pair_id)}")
    lines.append(f"rows_with_pnl: {sum(1 for row in evidence if row.pnl is not None)}")
    lines.append("")

    # === Matched pair summary (renamed/enhanced from old Pairing summary; P2-014B) ===
    lines.append("--- Matched pair summary ---")
    lines.append(f"Pairs found: {len(pairs)}")
    lines.append(f"Complete gross P/L pairs: {len(complete_gross)}")
    lines.append(f"Complete net P/L pairs with fees: {len(complete_net)}")
    lines.append(f"Incomplete pairs: {sum(1 for pair in pairs if pair.gross_pnl is None)}")

    methods: Dict[str, int] = {}
    for pair in pairs:
        methods[pair.method] = methods.get(pair.method, 0) + 1
    for method, count in sorted(methods.items()):
        lines.append(f"Pairing method {method}: {count} (method is locally derived matching; facts inside are direct where present)")

    for pair in pairs[:20]:
        pnl_label = "net (direct facts)" if pair.net_pnl is not None else ("gross (direct proceeds, fees missing)" if pair.gross_pnl is not None else "unavailable")
        lines.append(
            f"  {pair.method} {pair.entry.symbol or pair.exit.symbol or 'n/a'} "
            f"entry={relative(pair.entry.source, root)}:{pair.entry.row_number} "
            f"exit={relative(pair.exit.source, root)}:{pair.exit.row_number} "
            f"gross={money(pair.gross_pnl)} net={money(pair.net_pnl)} verdict={pair.verdict} [{pnl_label}]"
        )
    lines.append("")

    # legacy missing-field for compat
    missing_counts: Dict[str, int] = {}
    for row in evidence:
        for field in row.missing_fields:
            missing_counts[field] = missing_counts.get(field, 0) + 1

    lines.append("--- Missing-field diagnosis ---")
    if missing_counts:
        for field, count in sorted(missing_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"{field}: {count}")
    else:
        lines.append("No missing fields detected on classified entry/exit rows.")
    lines.append("")

    # Enhanced old verdict section (kept + improved language for compat)
    lines.append("--- Safe P/L reconstruction verdict ---")
    if complete_net:
        lines.append("Net P/L locally reconstructed from direct broker facts (buy_cost + sell_proceeds + fees present on pair).")
        lines.append(f"Reconstructable net pairs: {len(complete_net)} / {len(pairs)} paired cycles. (pairing method is local; facts are direct)")
    elif complete_gross:
        lines.append("Actual gross P/L can be reconstructed for some pairs, but net P/L remains unsafe because fee fields are incomplete.")
        lines.append(f"Reconstructable gross pairs: {len(complete_gross)} / {len(pairs)} paired cycles.")
    else:
        lines.append("P/L must remain n/a. No paired cycle has both actual buy cost and direct sell proceeds locally available.")
    lines.append("")

    lines.append("--- Logging gap to fix later, without live behavior changes now ---")
    lines.append("Log one immutable Coinbase fill record per order fill with order_id, client_order_id, product_id/symbol, side, status, filled_size, average_filled_price, gross quote value/proceeds, fee, created_at, filled_at, and strategy position/cycle id.")
    lines.append("Do not infer realized P/L from exit intent rows. Exit intent without fill/proceeds evidence is not enough for realized P/L. Use direct_broker_fact classification from reconciliation modules for future logger readiness.")

    return "\n".join(lines) + "\n"


def run_report(root: Path) -> str:
    root = root.resolve()
    profiles, evidence = scan(root)
    pairs = pair_rows(evidence)
    return render(root, profiles, evidence, pairs)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Advisory-only Coinbase fill/proceeds reconciliation report")
    parser.add_argument("--root", default=".", help="Repository root to inspect")
    args = parser.parse_args(argv)
    print(run_report(Path(args.root)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
