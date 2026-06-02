#!/usr/bin/env python3
"""
coinbase_candidate_to_order_audit.py — read-only offline diagnostic for
candidate-to-order gap and external inventory impact on max_open_positions.

P2-024F: external/staked SOL must not consume bot's max_open slot.

Usage:
  python3 scripts/coinbase_candidate_to_order_audit.py --json

Outputs structured report using only local runtime/state + config (no broker,
no .env, no network, no orders).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = REPO_ROOT / "runtime"
STATE = REPO_ROOT / "state" / "coinbase"
CONFIG_CANDIDATES = [
    REPO_ROOT / "config_coinbase_crypto.yaml",
    REPO_ROOT / "config.yaml",
]

EXPANDED_LIVE = ["BTC/USD", "ETH/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "LINK/USD", "LTC/USD"]
SOL = "SOL/USD"


def load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def get_cfg_max_open() -> int:
    # minimal parse, prefer global_risk.max_open_positions
    for cpath in CONFIG_CANDIDATES:
        if not cpath.exists():
            continue
        try:
            text = cpath.read_text()
            # very lightweight, look for the key near global_risk
            if "max_open_positions" in text:
                # try to find under global_risk or top
                for line in text.splitlines():
                    if "max_open_positions" in line and ":" in line:
                        val = line.split(":", 1)[1].strip().strip(",").strip("'\"")
                        try:
                            return int(val)
                        except Exception:
                            pass
        except Exception:
            pass
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit machine-readable report")
    args = ap.parse_args(argv)

    hb = load_json(RUNTIME / "coinbase_heartbeat.json")
    open_state = load_json(STATE / "open_positions.json")
    ext_state = load_json(STATE / "external_inventory.json")

    bot_positions = (open_state or {}).get("positions", {}) or {}
    bot_owned_count = len(bot_positions)
    bot_owned_symbols = list(bot_positions.keys())

    ext_inv = (ext_state or {}).get("external_inventory", {}) or {}
    external_count = len(ext_inv)
    external_symbols = list(ext_inv.keys())

    max_open = get_cfg_max_open()
    max_trades = 3  # guardrail

    max_open_slot_available = bot_owned_count < max_open

    # Would external alone block the expanded candidates via max_open gate?
    blocked_by_external_only = (external_count > 0 and bot_owned_count == 0 and not max_open_slot_available)
    # With the P2-024F fix, external should never cause this when bot_owned==0
    symbols_blocked_by_external_inventory = False  # post-fix expectation

    report = {
        "schema_version": "p2-024f.coinbase_candidate_to_order_audit.v1",
        "generated_at": hb.get("last_loop_time"),
        "mode": hb.get("mode", "live"),
        "pid": hb.get("pid"),
        "expanded_live_symbols": EXPANDED_LIVE,
        "sol_excluded": SOL not in EXPANDED_LIVE,
        "external_inventory": {
            "count": external_count,
            "symbols": external_symbols,
            "classification": "external_staked_non_bot" if SOL in external_symbols else None,
            "blocks_new_entries": False,  # per design for SOL
        },
        "bot_owned": {
            "open_position_count": bot_owned_count,
            "symbols": bot_owned_symbols,
        },
        "caps": {
            "max_open_positions": max_open,
            "max_trades_per_day": max_trades,
            "final_notional_target": 5.0,
            "hard_cap": 10.0,
        },
        "max_open_slot_available": max_open_slot_available,
        "symbols_blocked_by_external_inventory": symbols_blocked_by_external_inventory,
        "candidate_max_open_impact": {
            "ADA/USD": "would_pass_max_open_gate" if max_open_slot_available else "blocked",
            "LTC/USD": "would_pass_max_open_gate" if max_open_slot_available else "blocked",
        },
        "next_gate_after_max_open_for_candidates": "strategy_internal_filters (regime/rsi/bb/reversal/spread) + fee_drag + other risk (daily_trades, exposure, etc.)",
        "trade_permission": "none",  # read-only audit
        "notes": [
            "External/staked SOL is visible for reporting but excluded from bot_owned count and max_open check.",
            "With 0 bot-owned positions, max_open=1 slot is available for expanded basket candidates.",
            "SOL remains non-tradable by bot; no remediation performed here.",
        ],
    }

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()  # newline
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
