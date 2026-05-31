#!/usr/bin/env python3
"""
P2-011C — Coinbase Raw Payload Fixture Proof (read-only discovery only).

This script loads sanitized static fixtures representing Coinbase Advanced Trade
order and fills responses. It performs pure classification and analysis to prove
what direct broker facts are available for trustworthy gross/net P/L reconstruction.

No network calls. No secrets. No runtime changes. Pure analysis.

Run:
    python3 scripts/coinbase_raw_payload_fixture_proof.py

It produces docs/COINBASE_RAW_PAYLOAD_FIXTURE_PROOF.md when executed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "coinbase"
OUTPUT_MD = ROOT / "docs" / "COINBASE_RAW_PAYLOAD_FIXTURE_PROOF.md"


@dataclass
class FieldClassification:
    name: str
    value: Any
    classification: str  # "direct_broker_fact", "locally_derived", "unavailable", "unsafe_estimate"
    notes: str = ""


@dataclass
class PayloadAnalysis:
    payload_type: str
    source: str
    fields: List[FieldClassification] = field(default_factory=list)
    has_per_fill_breakdown: bool = False
    has_liquidity_indicator: bool = False
    has_stable_fill_id: bool = False
    idempotency_candidates: List[str] = field(default_factory=list)
    gross_pnl_reconstructible: bool = False
    net_pnl_reconstructible: bool = False
    notes: List[str] = field(default_factory=list)


def load_fixture(name: str) -> Dict[str, Any]:
    path = FIXTURES_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def classify_field(name: str, value: Any, context: str = "") -> FieldClassification:
    """Classify a field from a Coinbase payload."""
    if value in (None, "", "0", 0):
        return FieldClassification(name, value, "unavailable", "Field present but zero/empty in this example")

    # Known direct facts from Coinbase order object (per current broker_coinbase.py)
    direct_order_fields = {
        "filled_size", "average_filled_price", "filled_value",
        "total_fees", "status", "settled", "completion_percentage",
        "last_fill_time", "created_time"
    }

    if name in direct_order_fields:
        return FieldClassification(name, value, "direct_broker_fact",
                                   "Extracted directly from Coinbase order object in get_order response")

    # Per-fill level fields (from historical fills endpoint)
    if name in {"price", "size", "fee", "fee_currency", "liquidity_indicator", "trade_id", "entry_id"}:
        return FieldClassification(name, value, "direct_broker_fact",
                                   "Per-fill fact from /historical/fills (or equivalent)")

    if name in {"gross_quote_value", "net_quote_value"}:
        return FieldClassification(name, value, "locally_derived",
                                   "Would require calculation from size * price and fees")

    return FieldClassification(name, value, "unavailable", f"Unknown or not present in {context} payload")


def analyze_order_payload(order_resp: Dict[str, Any], label: str) -> PayloadAnalysis:
    analysis = PayloadAnalysis(payload_type="order_status", source=label)
    order = order_resp.get("order", order_resp)

    for key in ["filled_size", "average_filled_price", "filled_value", "total_fees",
                "status", "settled", "completion_percentage", "last_fill_time", "created_time"]:
        if key in order:
            analysis.fields.append(classify_field(key, order[key], "order"))

    # Derived for P/L
    try:
        size = float(order.get("filled_size", 0))
        avg_price = float(order.get("average_filled_price", 0))
        fees = float(order.get("total_fees", 0))
        if size > 0 and avg_price > 0:
            gross = size * avg_price
            analysis.fields.append(FieldClassification("gross_quote_value", gross, "locally_derived",
                                                       "size * average_filled_price (reconstructible)"))
            analysis.fields.append(FieldClassification("net_quote_value", gross - fees, "locally_derived",
                                                       "gross - total_fees (reconstructible from this payload)"))
            analysis.gross_pnl_reconstructible = True
            analysis.net_pnl_reconstructible = True
    except Exception:
        pass

    analysis.notes.append("Order-level payload provides good cumulative facts for the final fill state.")
    analysis.notes.append("No per-fill breakdown or liquidity role per individual fill in this payload.")
    return analysis


def analyze_fills_payload(fills_resp: Dict[str, Any], label: str) -> PayloadAnalysis:
    analysis = PayloadAnalysis(payload_type="historical_fills", source=label)
    fills = fills_resp.get("fills", [])

    if not fills:
        analysis.notes.append("No fills in payload")
        return analysis

    analysis.has_per_fill_breakdown = True

    for f in fills:
        for key in ["price", "size", "fee", "fee_currency", "liquidity_indicator", "trade_id", "entry_id", "order_id"]:
            if key in f:
                cl = classify_field(key, f[key], "fill")
                analysis.fields.append(cl)
                if key in ("trade_id", "entry_id"):
                    analysis.has_stable_fill_id = True
                    analysis.idempotency_candidates.append(f"{key}={f[key]}")

        # Check for liquidity
        if "liquidity_indicator" in f:
            analysis.has_liquidity_indicator = True

    analysis.notes.append("Fills list provides per-fill price, size, fee, and liquidity role.")
    analysis.notes.append("Strong candidate for stable idempotency when combining order_id + trade_id/entry_id.")
    return analysis


def run_full_proof() -> Dict[str, Any]:
    results: Dict[str, Any] = {}

    # Fixture 1: Order-level only (current reality in the bot)
    order_buy = load_fixture("sample_order_filled_buy.json")
    order_analysis = analyze_order_payload(order_buy, "sample_order_filled_buy")
    results["order_level_only"] = order_analysis

    # Fixture 2: With fills list (hypothetical future)
    fills = load_fixture("sample_fills_list.json")
    fills_analysis = analyze_fills_payload(fills, "sample_fills_list")
    results["fills_list"] = fills_analysis

    # Combined assessment for the 15 points
    assessment = {
        "1_order_status_payload_exists": True,
        "2_historical_fills_payload_available_in_codebase": False,  # No code currently calls it
        "3_filled_size_direct": True,
        "4_average_filled_price_direct": True,
        "5_per_fill_price_size_available": fills_analysis.has_per_fill_breakdown,
        "6_actual_fees_direct": True,  # total_fees on order; per-fill fee in fills list
        "7_direct_sell_proceeds": False,  # Not proven in current order status path for exit orders (no polling)
        "8_maker_taker_liquidity_per_fill": fills_analysis.has_liquidity_indicator,
        "9_partial_fills_representation": "order_summary_only (completion_percentage + cumulative fields). No multi-fill records in current order payload.",
        "10_stable_idempotency_key_proven": fills_analysis.has_stable_fill_id,
        "11_idempotency_candidate": "order_id + (trade_id or entry_id) from fills list. order_id alone is insufficient for multi-fill orders.",
        "12_duplicate_prevention_from_polling": "Possible with order_id + status + last_update_time or a processed set.",
        "13_current_csv_logger_safe": False,  # Because sell proceeds and stable fill-level keys not proven for exit legs
        "14_recommended_architecture": [
            "order/status REST for entry and exit order final state (good for cumulative)",
            "historical_fills REST for detailed per-fill breakdown + fees + liquidity (needed for high confidence P/L)",
            "Do NOT rely solely on order summary for exits if per-fill fee/liquidity matters",
        ],
        "15_blocked_reasons": []
    }

    if not assessment["7_direct_sell_proceeds"]:
        assessment["15_blocked_reasons"].append("Direct sell proceeds not proven from current broker response handling for exit orders.")
    if not assessment["10_stable_idempotency_key_proven"]:
        assessment["15_blocked_reasons"].append("Stable fill-level idempotency key (trade_id/entry_id) not proven without calling historical fills endpoint.")

    results["assessment"] = assessment
    return results


def generate_report(results: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# P2-011C — Coinbase Raw Payload Fixture Proof")
    lines.append("")
    lines.append("**ADVISORY / READ-ONLY / STATIC FIXTURES ONLY**")
    lines.append("Generated by scripts/coinbase_raw_payload_fixture_proof.py")
    lines.append("")
    lines.append("This report uses sanitized representative fixtures to analyze what direct broker facts Coinbase makes available.")
    lines.append("")

    assessment = results["assessment"]

    lines.append("## Executive Summary")
    lines.append("")
    if assessment["15_blocked_reasons"]:
        lines.append("**CONCLUSION: Live logger hook remains BLOCKED.**")
        for r in assessment["15_blocked_reasons"]:
            lines.append(f"- {r}")
    else:
        lines.append("**Sufficient facts proven for safe hook.**")
    lines.append("")

    lines.append("## Key Determinations (15 Points)")

    lines.append("1. Order/status payload: **Available and used today** via `get_order`.")
    lines.append("2. Historical fills payload: **Not called anywhere in current codebase**.")
    lines.append(f"3. filled_size is direct broker fact: **Yes** (order object).")
    lines.append(f"4. average_filled_price is direct broker fact: **Yes** (order object).")
    lines.append(f"5. Per-fill price/size available: **{'Yes (in fills list fixture)' if assessment['5_per_fill_price_size_available'] else 'No (order summary only)'}**.")
    lines.append(f"6. Actual fees are direct: **Yes** (total_fees on order; per-fill fee in fills list).")
    lines.append(f"7. Direct sell proceeds: **No** — not proven. Current code never polls exit order status for filled_value/total_fees on sell legs.")
    lines.append(f"8. Maker/taker (liquidity_indicator) per fill: **{'Yes (in fills list)' if assessment['8_maker_taker_liquidity_per_fill'] else 'Not present in order-level payload'}**.")
    lines.append(f"9. Partial fills: **Order summary only** (completion_percentage + cumulative fields). No multi-record fill list in order payload.")
    lines.append(f"10. Stable fill-level idempotency key proven: **{'Yes (trade_id/entry_id in fills list)' if assessment['10_stable_idempotency_key_proven'] else 'No — requires historical fills endpoint'}**.")
    lines.append(f"11. Recommended idempotency: {assessment['11_idempotency_candidate']}")
    lines.append("12. Duplicate prevention from polling: Possible using order_id + last_update_time or processed set.")
    lines.append(f"13. Current CSV logger hook safe today: **No** — blocked by missing sell proceeds proof and lack of proven stable fill-level keys for exits.")
    lines.append("14. Recommended architecture:")
    for item in assessment["14_recommended_architecture"]:
        lines.append(f"   - {item}")
    lines.append("15. Other notes: See detailed fixture analysis below.")
    lines.append("")

    lines.append("## Fixture Analysis")
    for key, analysis in results.items():
        if isinstance(analysis, PayloadAnalysis):
            lines.append(f"### {analysis.source} ({analysis.payload_type})")
            for f in analysis.fields:
                lines.append(f"- {f.name}: {f.classification} — {f.notes}")
            for n in analysis.notes:
                lines.append(f"  > {n}")
            lines.append("")

    lines.append("## Final Safety Verdict")
    lines.append("")
    if assessment["15_blocked_reasons"]:
        lines.append("**The live append of coinbase_fill_logger remains BLOCKED.**")
        lines.append("Reason: Actual per-leg fees/proceeds and/or stable fill-level idempotency keys are not proven from current response paths for both entry and exit orders.")
    else:
        lines.append("Sufficient facts exist for a narrow, guarded hook.")
    lines.append("")
    lines.append("---")
    lines.append("P2-011C proof complete. No execution changes. No live hooks.")
    return "\n".join(lines)


def main() -> None:
    results = run_full_proof()
    report = generate_report(results)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(f"Wrote {OUTPUT_MD}")
    print("P2-011C raw payload fixture proof complete (read-only).")


if __name__ == "__main__":
    main()
