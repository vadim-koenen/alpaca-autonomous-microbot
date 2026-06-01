#!/usr/bin/env python3
"""
P2-019D — Offline Operator Daily Digest Generator (GREEN, strictly offline).

Produces a concise daily status summary (text + JSON) from local artifacts only.
No broker calls, no .env reads, no file writes except stdout.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_sol_position(positions):
    for p in positions or []:
        if isinstance(p, dict):
            sym = (p.get("symbol") or p.get("product_id") or "").upper()
            if "SOL" in sym:
                return p
    return None


def build_digest(probe_path: Path) -> Dict[str, Any]:
    probe = _safe_load_json(probe_path) or {}

    broker_truth = bool(probe.get("broker_read_successful"))
    sol_on_broker = probe.get("sol_on_broker")

    positions = probe.get("open_positions_on_broker") or []
    sol_pos = _find_sol_position(positions)
    sol_qty = None
    if sol_pos:
        try:
            sol_qty = float(sol_pos.get("qty") or 0)
        except Exception:
            sol_qty = None

    fills = probe.get("recent_fills_sample") or []
    matched = next((f for f in fills if isinstance(f, dict) and f.get("trade_id") == "1f10a7cb-3fe5-4cbb-b990-f74c39529fc9"), None)

    entry_facts = False
    if matched:
        entry_facts = (matched.get("fee") is not None and matched.get("fee") != "") and \
                      (matched.get("filled_value") is not None and matched.get("filled_value") != "")

    net_pnl = False  # exit facts not reliably present in current snapshot
    aggregation = net_pnl and not sol_on_broker
    scaling = False

    text = f"""=== Operator Daily Digest (P2-019D) ===
Generated: {datetime.now(timezone.utc).isoformat()}

Main status:
- Profit readout: unsafe_to_aggregate
- SOL held on broker: {sol_on_broker} (qty={sol_qty})
- Broker truth available: {broker_truth}

Evidence gate:
- Entry direct facts complete: {entry_facts}
- Exit direct facts complete: {False}
- Aggregation allowed: {aggregation}
- Scaling allowed: {scaling}

Current blocker: SOL still held with incomplete fee/filled_value evidence for the matched trade.

Next safe action: Continue controlled read-only deeper payload capture for entry and exit legs only.

WARNING: DO NOT SCALE RISK. DO NOT CLOSE AUTOMATICALLY. Human approval required for any remediation.

Review branches to watch (do not merge without explicit approval):
- P2-017D (full payload capture)
- P2-018E (review gate expansion)
"""

    json_out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "main_head": "see git log",
        "profit_readout": "unsafe_to_aggregate",
        "sol_status": {"held_on_broker": sol_on_broker, "qty": sol_qty},
        "broker_truth_available": broker_truth,
        "evidence_gate": {
            "entry_facts_complete": entry_facts,
            "exit_facts_complete": False,
            "net_pnl_available": net_pnl,
            "aggregation_allowed": aggregation,
            "scaling_allowed": scaling,
        },
        "review_branches": ["P2-017D", "P2-018E"],
        "next_safe_action": "Continue controlled read-only deeper payload capture for entry and exit legs only.",
        "warnings": ["DO NOT SCALE RISK", "DO NOT CLOSE AUTOMATICALLY", "Human approval required for any remediation"],
    }

    return {"text": text, "json": json_out}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-json", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    out = build_digest(args.probe_json)

    if args.json:
        print(json.dumps(out["json"], indent=2, default=str))
    else:
        print(out["text"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
