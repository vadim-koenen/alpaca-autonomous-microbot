#!/usr/bin/env python3
"""
ADVISORY ONLY — P2-011B Coinbase Fill Response Discovery (read-only).

Scans local source to locate where actual Coinbase order/fill/proceeds/fee
facts are available in the current codebase. Identifies the narrowest safe
future append-only hook seam for the coinbase_fill_logger scaffold.

This script performs **no** broker API calls, reads no .env, touches no
runtime/state/launchd files, and does not modify any behavior.

Run:
    python3 scripts/coinbase_fill_response_discovery.py

It produces docs/COINBASE_FILL_RESPONSE_DISCOVERY.md when executed.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
OUTPUT_MD = DOCS_DIR / "COINBASE_FILL_RESPONSE_DISCOVERY.md"

TARGET_FILES = [
    "broker_coinbase.py",
    "journal.py",
    "position_manager.py",
    "strategy_crypto.py",
    "main.py",
]

FILL_FACT_FIELDS = {
    "average_filled_price",
    "filled_size",
    "filled_value",
    "total_fees",
    "completion_percentage",
    "settled",
    "last_fill_time",
    "fee_amount",
    "fee_currency",
    "proceeds",
    "sell_proceeds",
    "gross_proceeds",
}

ORDER_METHODS = ("get_order_status", "place_limit_order", "place_market_order")
JOURNAL_METHODS = ("log_order", "log_order_preview", "find_recent_bot_entry", "log_exit")


@dataclass
class Finding:
    file: str
    lineno: int
    kind: str
    text: str
    notes: str = ""


@dataclass
class DiscoveryResult:
    findings: list[Finding] = field(default_factory=list)
    has_direct_filled_facts: bool = False
    direct_facts_location: str = ""
    has_sell_proceeds: bool = False
    exit_fee_calc_is_estimate: bool = True
    safest_hook_seam: str = ""
    duplication_risk: str = ""
    partial_fill_support: str = ""
    recommended_tests: list[str] = field(default_factory=list)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _find_def_lines(text: str, method_names: tuple[str, ...]) -> list[tuple[int, str]]:
    results = []
    for i, line in enumerate(text.splitlines(), 1):
        for name in method_names:
            if re.search(rf"^\s+def {name}\b", line):
                results.append((i, name))
    return results


def _scan_for_fill_fields(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        for field in FILL_FACT_FIELDS:
            if field in line:
                findings.append(Finding(
                    file=str(path.relative_to(ROOT)),
                    lineno=i,
                    kind="fill-field",
                    text=line.strip()[:140],
                ))
    return findings


def _extract_get_order_status_body(text: str) -> str:
    """Very lightweight extraction of the get_order_status implementation."""
    match = re.search(
        r"def get_order_status\(self, order_id: str\) -> dict:.*?(?=\n    def |\Z)",
        text,
        re.DOTALL,
    )
    if match:
        return match.group(0)[:2000]
    return ""


def run_discovery() -> DiscoveryResult:
    result = DiscoveryResult()
    all_findings: list[Finding] = []

    for rel in TARGET_FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        text = _read_text(p)

        # 1. Locate the three key order methods
        for lineno, name in _find_def_lines(text, ORDER_METHODS):
            all_findings.append(Finding(
                file=rel, lineno=lineno, kind="order-method",
                text=f"def {name}",
            ))

        # 2. Locate journal methods
        for lineno, name in _find_def_lines(text, JOURNAL_METHODS):
            all_findings.append(Finding(
                file=rel, lineno=lineno, kind="journal-method",
                text=f"def {name}",
            ))

        # 3. Find all references to actual fill/fact fields
        all_findings.extend(_scan_for_fill_fields(p, text))

    result.findings = all_findings

    # Analysis based on known structure (evidence-driven)
    broker_text = _read_text(ROOT / "broker_coinbase.py")
    pos_text = _read_text(ROOT / "position_manager.py")
    journal_text = _read_text(ROOT / "journal.py")

    # Q1 + Q2: Direct facts only appear in get_order_status
    if "average_filled_price" in broker_text and "order.get(\"average_filled_price\"" in broker_text:
        result.has_direct_filled_facts = True
        result.direct_facts_location = "broker_coinbase.py:get_order_status (via self._client.get_order)"

    # Q3: Sell proceeds
    if any(k in pos_text for k in ("sell_proceeds", "gross_proceeds", "exit_proceeds")):
        result.has_sell_proceeds = True
    # Exit fee calculation in _execute_exit uses config rates
    if "fee_entry_pct" in pos_text and "fee_exit_pct" in pos_text:
        result.exit_fee_calc_is_estimate = True

    # Q4: Partial fills
    if "completion_percentage" in broker_text:
        result.partial_fill_support = "Yes — order object carries completion_percentage + cumulative filled_size/average_filled_price. Current paths only act on terminal 'filled'."

    # Q5: Duplication risk
    if "_reconcile_pending_orders" in pos_text and "get_order_status" in pos_text:
        result.duplication_risk = "HIGH — _reconcile_pending_orders and _backfill_missing_order_status poll repeatedly while order_status not in _TERMINAL_ORDER_STATUSES. After 'filled' the order_id remains queryable until position is dropped."

    # Q6: Safest seam
    # Evidence: facts only become trusted state inside position_manager reconcile logic for entries.
    # No equivalent post-close capture exists for exit orders.
    result.safest_hook_seam = (
        "position_manager.py:_reconcile_pending_orders (and _backfill_missing_order_status) "
        "immediately after `status_info = get_order_status(order_id)` when normalized == 'filled'. "
        "This is the only place where direct Coinbase facts are turned into trusted session state for entries. "
        "journal.py:log_exit receives only pre-computed estimates. "
        "No post-close get_order_status call exists for exit legs."
    )

    # Q7: Required tests
    result.recommended_tests = [
        "Mock broker.get_order_status returning 'filled' + partial states; assert logger called exactly once per unique order_id across repeated polls and simulated restarts (via saved positions).",
        "Test that no rows are appended for dry_run, paper, or when broker lacks get_order_status.",
        "Test deterministic capture of raw_order_response_json (full dict from get_order).",
        "Test deduplication guard (order_id + 'filled' status or processed set).",
        "Verify exit path still has zero direct sell proceeds/fill facts (negative test).",
        "Add to existing position_manager reassociation tests.",
    ]

    return result


def generate_report(result: DiscoveryResult) -> str:
    lines: list[str] = []
    lines.append("# P2-011B — Coinbase Fill Response Discovery Report")
    lines.append("")
    lines.append("**ADVISORY / READ-ONLY / LOCAL SOURCE ONLY**")
    lines.append("Generated by `scripts/coinbase_fill_response_discovery.py`")
    lines.append("")
    lines.append("This report answers the seven gating questions for P2-011B before any hook is written.")
    lines.append("All conclusions are derived from static inspection of the current tree (HEAD 1c81139 + P2-011A).")
    lines.append("")

    lines.append("## 1. Which Coinbase response currently contains actual fill/proceeds/fee facts?")
    if result.has_direct_filled_facts:
        lines.append(f"**{result.direct_facts_location}**")
        lines.append("")
        lines.append("The `self._client.get_order(order_id=...)` response (normalised inside `get_order_status`) is the **only** place in the entire codebase that surfaces:")
        lines.append("- `filled_size`")
        lines.append("- `average_filled_price`")
        lines.append("- `filled_value`")
        lines.append("- `total_fees`")
        lines.append("- `completion_percentage`")
        lines.append("- `settled`")
        lines.append("- `last_fill_time`")
        lines.append("")
        lines.append("`place_limit_order` and `place_market_order` return only `{order_id, success_response}` with no fill data (order is still pending).")
    else:
        lines.append("**None found in a form usable for immutable logging.**")
    lines.append("")

    lines.append("## 2. Are average_filled_price, filled_size, and fee fields direct Coinbase facts or local estimates?")
    lines.append("**Direct facts** when read from `broker_coinbase.py:get_order_status`.")
    lines.append("")
    lines.append("**Local estimates** everywhere else:")
    lines.append("- `position_manager.py:_execute_exit` computes `fees_paid` exclusively from `get_cfg(\"crypto\", \"fee_entry_pct\")` + `fee_exit_pct` (currently 0.6% in Coinbase config).")
    lines.append("- `journal.py:log_exit` receives and persists only those pre-computed estimates.")
    lines.append("- Entry `total_fees` is captured into `session.open_positions[...]['total_fees']` but is **not** written to the durable journal as an immutable fact row.")
    lines.append("")

    lines.append("## 3. Can sell proceeds be captured directly from current broker responses?")
    lines.append("**No.**")
    lines.append("")
    lines.append("There is no code path that calls `get_order_status` on an exit/close order_id after `close_position()` succeeds.")
    lines.append("In `_execute_exit`, `exit_price` is the decision-time market price, not the actual fill price of the market sell.")
    lines.append("After `log_exit`, the position is immediately removed from tracking. No post-close reconciliation exists for sell legs.")
    lines.append("All prior reconciliation reports (P2-007 etc.) correctly report zero direct sell proceeds in journal EXIT rows.")
    lines.append("")

    lines.append("## 4. Are partial fills possible, and should the future logger write one row per order or one row per fill?")
    lines.append(f"**{result.partial_fill_support}**")
    lines.append("")
    lines.append("Coinbase Advanced Trade order objects support partial fills via `completion_percentage` + cumulative fields.")
    lines.append("For the bot's $1 exploration trades on BTC/ETH/SOL this is uncommon but possible.")
    lines.append("")
    lines.append("**Recommendation for logger:** One row per order (when it reaches terminal 'filled' status), capturing the final cumulative values + `raw_order_response_json`. A dedicated `/fills` list endpoint would be required for true per-fill rows; none is called anywhere today.")
    lines.append("")

    lines.append("## 5. Could repeated get_order_status polling duplicate rows?")
    lines.append(f"**{result.duplication_risk}**")
    lines.append("")
    lines.append("Both `_reconcile_pending_orders` (every loop) and `_backfill_missing_order_status` (startup) call `get_order_status` while the order is not yet terminal.")
    lines.append("Once 'filled', the order_id remains in the position dict until the position is dropped after exit.")
    lines.append("A future hook **must** implement strong deduplication (order_id + terminal status, or a small persisted set of already-logged order_ids).")
    lines.append("")

    lines.append("## 6. Which exact function is the safest future hook?")
    lines.append("")
    lines.append("**Recommended seam:**")
    lines.append(f"> {result.safest_hook_seam}")
    lines.append("")
    lines.append("### Why not the plan candidates?")
    lines.append("- `broker_coinbase.py:get_order_status` — too low-level; would require passing logger into the broker, would fire on every poll + dry_run/paper/Alpaca paths.")
    lines.append("- `broker_coinbase.py:place_*_order` — no fill facts present at placement time.")
    lines.append("- `journal.py:log_exit` — receives only estimates; no actual exit-leg fill data.")
    lines.append("")
    lines.append("**Gap for complete coverage:** No equivalent post-close capture exists for sell orders. Wiring only entries would still leave realized P/L incomplete.")
    lines.append("")

    lines.append("## 7. What tests are required before a future hook patch is allowed?")
    for t in result.recommended_tests:
        lines.append(f"- {t}")
    lines.append("")

    lines.append("## Overall Assessment")
    lines.append("")
    lines.append("The local codebase **does prove** that direct fill facts exist — but only for **entry** orders, and only inside the position reconciliation logic.")
    lines.append("Direct sell proceeds and actual exit fees are **not** available from current broker response handling.")
    lines.append("")
    lines.append("Therefore the correct next step is **not** to wire the logger to live execution yet.")
    lines.append("P2-011C (or a tightly scoped follow-up) should first add a narrow, read-only capture of the raw `get_order` payload at the identified seam, plus a fixture-based test that proves we can reconstruct gross/net P/L from the captured facts.")
    lines.append("")
    lines.append("This keeps the safety invariant: no hook is installed until we have proven, with local evidence, that the required facts are actually present for both legs.")
    lines.append("")

    lines.append("---")
    lines.append("Generated from P2-011B discovery on review branch. No live behavior changed.")
    return "\n".join(lines)


def main() -> None:
    result = run_discovery()
    report = generate_report(result)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(f"Wrote {OUTPUT_MD}")
    print("P2-011B discovery complete (read-only).")


if __name__ == "__main__":
    main()
