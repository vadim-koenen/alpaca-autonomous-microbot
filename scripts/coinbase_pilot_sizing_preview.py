#!/usr/bin/env python3
"""
Offline Coinbase balance-relative pilot sizing preview.

Reads only local config and supplied numeric arguments. It does not import
broker clients, read .env, call APIs, place orders, or mutate state/logs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import yaml

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT))

from coinbase_fee_aware_pilot import resolve_balance_relative_pilot_sizing


def _load_config(path: Path) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def build_preview(
    *,
    equity: Any,
    buying_power: Any,
    config_path: Path = ROOT / "config_coinbase_crypto.yaml",
) -> Dict[str, Any]:
    config = _load_config(config_path)
    crypto = config.get("crypto") if isinstance(config.get("crypto"), dict) else {}
    global_risk = config.get("global_risk") if isinstance(config.get("global_risk"), dict) else {}

    sizing = resolve_balance_relative_pilot_sizing(
        equity=equity,
        buying_power=buying_power,
        pilot_trade_percent_of_balance=crypto.get("pilot_trade_percent_of_balance", 0.10),
        min_trade_notional_usd=crypto.get("min_trade_notional_usd", 5.00),
        max_trade_notional_usd=crypto.get("max_trade_notional_usd", 10.00),
        absolute_hard_trade_cap_usd=crypto.get("absolute_hard_trade_cap_usd", 10.00),
        balance_basis=crypto.get("balance_basis", "buying_power_then_equity"),
    )
    eligible = list(crypto.get("fee_aware_pilot_symbols") or ["BTC/USD", "ETH/USD"])
    excluded = list(crypto.get("fee_aware_pilot_excluded_symbols") or ["SOL/USD"])

    return {
        "verdict": sizing.get("verdict", "BLOCKED"),
        "reason": sizing.get("reason"),
        "effective_balance": sizing.get("effective_balance"),
        "balance_basis": sizing.get("balance_basis"),
        "balance_source": sizing.get("balance_source"),
        "pilot_trade_percent_of_balance": sizing.get("pilot_trade_percent_of_balance"),
        "target_trade_notional": sizing.get("target_trade_notional"),
        "final_trade_notional": sizing.get("final_trade_notional"),
        "min_trade_notional_usd": sizing.get("min_trade_notional_usd"),
        "max_trade_notional_usd": sizing.get("max_trade_notional_usd"),
        "absolute_hard_trade_cap_usd": sizing.get("absolute_hard_trade_cap_usd"),
        "hard_cap_notional_usd": sizing.get("hard_cap_notional_usd"),
        "min_trade_floor_applied": sizing.get("min_trade_floor_applied", False),
        "eligible_symbols": eligible,
        "excluded_symbols": excluded,
        "max_open_positions": global_risk.get("max_open_positions"),
        "max_trades_per_day": global_risk.get("max_trades_per_day"),
        "risk_increase": "not_approved",
        "scaling_allowed": False,
        "scaling_mode": "balance_relative_capped_pilot",
        "safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "secrets_or_env_read": False,
            "orders_cancels_closes_modifications": False,
            "state_or_log_mutation": False,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Preview Coinbase capped balance-relative pilot sizing")
    parser.add_argument("--equity", required=True, help="Account equity snapshot")
    parser.add_argument("--buying-power", required=True, help="Account buying power snapshot")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config_coinbase_crypto.yaml",
        help="Local Coinbase config path",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    preview = build_preview(equity=args.equity, buying_power=args.buying_power, config_path=args.config)
    if args.json:
        print(json.dumps(preview, indent=2, sort_keys=True))
    else:
        print("=== Coinbase Pilot Sizing Preview ===")
        print(f"Verdict: {preview['verdict']}")
        print(f"Effective balance: {preview['effective_balance']}")
        print(f"Target notional: {preview['target_trade_notional']}")
        print(f"Final notional: {preview['final_trade_notional']}")
        print(f"Hard cap: {preview['absolute_hard_trade_cap_usd']}")
        print(f"Eligible symbols: {', '.join(preview['eligible_symbols'])}")
        print(f"Excluded symbols: {', '.join(preview['excluded_symbols'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
