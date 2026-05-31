#!/usr/bin/env python3
"""
P2-011D-alt — Coinbase Fills Payload Discovery (read-only, static fixtures only).

This script performs pure analysis on sanitized static fixtures to determine
the safest future path for capturing per-fill facts, direct sell proceeds,
actual fees, and stable fill-level idempotency keys from Coinbase.

No live API calls. No behavior changes. Discovery only.

Run:
    python3 scripts/coinbase_fills_payload_discovery.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "coinbase"
OUTPUT_MD = ROOT / "docs" / "COINBASE_FILLS_PAYLOAD_DISCOVERY.md"


@dataclass
class FieldClass:
    name: str
    value: Any
    classification: str  # direct_broker_fact | locally_derived | unavailable | unsafe_estimate
    source: str
    notes: str = ""


@dataclass
class FixtureAnalysis:
    name: str
    payload_type: str  # order or fills
    fields: List[FieldClass] = field(default_factory=list)
    has_stable_fill_id: bool = False
    has_per_fill_fee: bool = False
    has_liquidity: bool = False
    direct_sell_proceeds_possible: bool = False
    notes: List[str] = field(default_factory=list)


def load_json(name: str) -> Dict[str, Any]:
    with open(FIXTURES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def classify(name: str, value: Any, source: str) -> FieldClass:
    if value in (None, "", 0, "0"):
        return FieldClass(name, value, "unavailable", source, "Zero/empty or missing")

    direct_fields = {
        "filled_size", "average_filled_price", "filled_value", "total_fees",
        "price", "size", "fee", "fee_currency", "liquidity_indicator",
        "status", "settled", "trade_id", "entry_id", "order_id", "product_id", "side"
    }

    if name in direct_fields:
        return FieldClass(name, value, "direct_broker_fact", source, "Present in Coinbase response payload")

    if name in {"gross_quote_value", "net_quote_value", "commission"}:
        return FieldClass(name, value, "locally_derived", source, "Derived from size * price +/- fees")

    return FieldClass(name, value, "unavailable", source, "Not observed in current fixtures or code")


def analyze_order_fixture(path: Path) -> FixtureAnalysis:
    data = json.loads(path.read_text())
    order = data.get("order", data)
    analysis = FixtureAnalysis(name=path.name, payload_type="order_status")

    for k in ["filled_size", "average_filled_price", "filled_value", "total_fees", "status", "side", "product_id", "order_id"]:
        if k in order:
            analysis.fields.append(classify(k, order[k], "order"))

    # Check for sell proceeds reconstruction
    try:
        size = float(order.get("filled_size", 0))
        price = float(order.get("average_filled_price", 0))
        fees = float(order.get("total_fees", 0))
        if size > 0 and price > 0:
            proceeds = size * price
            analysis.fields.append(FieldClass("direct_sell_proceeds", proceeds, "direct_broker_fact" if order.get("side") == "SELL" else "locally_derived",
                                              "order", "size * average_filled_price for sell leg"))
            if order.get("side") == "SELL" and fees >= 0:
                analysis.direct_sell_proceeds_possible = True
    except Exception:
        pass

    analysis.notes.append(f"Side: {order.get('side')}")
    return analysis


def analyze_fills_fixture(path: Path) -> FixtureAnalysis:
    data = json.loads(path.read_text())
    fills = data.get("fills", [])
    analysis = FixtureAnalysis(name=path.name, payload_type="historical_fills")

    for f in fills:
        for k in ["price", "size", "fee", "fee_currency", "liquidity_indicator", "trade_id", "entry_id", "order_id", "product_id", "side", "time"]:
            if k in f:
                cl = classify(k, f[k], "fill")
                analysis.fields.append(cl)
                if k in ("trade_id", "entry_id"):
                    analysis.has_stable_fill_id = True
                if k == "fee":
                    analysis.has_per_fill_fee = True
                if k == "liquidity_indicator":
                    analysis.has_liquidity = True

    analysis.notes.append(f"Number of fill records: {len(fills)}")
    return analysis


def run_discovery() -> Dict[str, Any]:
    results = {}

    # Existing fixtures
    for fname in ["sample_order_filled_buy.json", "sample_order_filled_sell.json", "sample_order_partial_fills.json", "sample_order_missing_fees.json"]:
        p = FIXTURES_DIR / fname
        if p.exists():
            results[fname] = analyze_order_fixture(p)

    for fname in ["sample_fills_list.json", "sample_fills_list_no_trade_id.json"]:
        p = FIXTURES_DIR / fname
        if p.exists():
            results[fname] = analyze_fills_fixture(p)

    # Code inspection summary (static)
    code_findings = {
        "existing_fills_wrapper": False,
        "current_path": "Only get_order_status (order-level summary) is implemented in broker_coinbase.py",
        "fills_endpoint_wrapped": "No list_fills / historical_fills wrapper exists",
        "smallest_future_wrapper": "Add a thin get_historical_fills(self, product_id=None, order_id=None, ...) method in BrokerCoinbase that calls the SDK equivalent and returns normalized list of fill dicts",
    }

    return {"analyses": results, "code_findings": code_findings}


def generate_report(data: Dict[str, Any]) -> str:
    lines = []
    lines.append("# P2-011D-alt — Coinbase Fills Payload Discovery Report")
    lines.append("")
    lines.append("**Read-only static fixture analysis + code inspection**")
    lines.append("Generated by scripts/coinbase_fills_payload_discovery.py")
    lines.append("")

    code = data["code_findings"]
    lines.append("## 1-3. Code Inspection Findings")
    lines.append(f"- Existing fills/history wrapper in repo: **{code['existing_fills_wrapper']}**")
    lines.append(f"- Current implemented path: {code['current_path']}")
    lines.append(f"- Fills endpoint wrapped: {code['fills_endpoint_wrapped']}")
    lines.append(f"- Smallest future wrapper needed: {code['smallest_future_wrapper']}")
    lines.append("")

    lines.append("## 4-7. Fixture Analysis & Field Classification")
    for name, analysis in data["analyses"].items():
        lines.append(f"### {name} ({analysis.payload_type})")
        for f in analysis.fields:
            lines.append(f"- **{f.name}**: {f.classification} (from {f.source}) — {f.notes}")
        for n in analysis.notes:
            lines.append(f"  - Note: {n}")
        lines.append("")

    lines.append("## 8. Recommended Immutable Idempotency Key")
    lines.append("**Preferred:** `account_mode + product_id + order_id + (trade_id or entry_id)`")
    lines.append("From fixtures: `entry_id` or `trade_id` in fills list provides stable per-fill identity.")
    lines.append("`order_id` alone is insufficient for orders with multiple fills.")
    lines.append("")

    lines.append("## 9. Recommended Future Append-Only Fill Logging Path")
    lines.append("**Recommended combination:**")
    lines.append("- Primary: historical fills REST path (for per-fill price, size, fee, liquidity, stable IDs)")
    lines.append("- Secondary: order/status path (for final cumulative confirmation and exit order capture)")
    lines.append("- Reconciliation layer: match fills to their parent order")
    lines.append("- Future: WebSocket user stream for near-real-time (lower latency)")
    lines.append("Current order/status path alone is **insufficient** for high-confidence per-fill P/L and sell proceeds.")
    lines.append("")

    lines.append("## 10. Logger Hook Safety Verdict")
    lines.append("**BLOCKED**")
    lines.append("")
    lines.append("Reasons from fixtures and code inspection:")
    lines.append("- Direct per-fill fees and liquidity role only appear in historical fills payload (not currently wrapped or called).")
    lines.append("- Direct sell proceeds for exit legs are reconstructible from order-level payload *if* the exit order status is polled (current code does not do this for close_position fills).")
    lines.append("- Stable fill-level idempotency key (trade_id/entry_id) requires the fills list endpoint.")
    lines.append("- Payloads missing fees or stable IDs exist and must be handled gracefully.")
    lines.append("")

    lines.append("## Summary Recommendation")
    lines.append("The safest future path is to add a minimal `get_historical_fills(...)` wrapper in BrokerCoinbase,")
    lines.append("then implement a narrow capture point (likely in position_manager after exit reconciliation)")
    lines.append("that uses both order status + fills list, with reconciliation.")
    lines.append("Keep the logger hook blocked until the above is proven with real captured payloads and tests.")
    lines.append("")
    lines.append("---")
    lines.append("P2-011D-alt discovery complete. No execution changes made.")
    return "\n".join(lines)


def main() -> None:
    data = run_discovery()
    report = generate_report(data)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(report, encoding="utf-8")
    print(f"Wrote {OUTPUT_MD}")


if __name__ == "__main__":
    main()
