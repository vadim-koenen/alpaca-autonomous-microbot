#!/usr/bin/env python3
"""Secret-safe Alpaca auth/config diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import (  # noqa: E402
    get_config_path,
    get_mode,
    is_live_trading_enabled,
    is_paper,
    load_config,
    load_env,
)


def _present(name: str) -> bool:
    return bool(os.environ.get(name, ""))


def collect_diagnostics(mode_override: str | None = None) -> dict:
    load_env()
    cfg = load_config()
    if mode_override:
        cfg["mode"] = mode_override
    paper = is_paper()
    preferred_key = "ALPACA_PAPER_API_KEY" if paper else "ALPACA_LIVE_API_KEY"
    preferred_secret = "ALPACA_PAPER_SECRET_KEY" if paper else "ALPACA_LIVE_SECRET_KEY"
    fallback_key = "ALPACA_API_KEY"
    fallback_secret = "ALPACA_SECRET_KEY"
    using_preferred = _present(preferred_key) or _present(preferred_secret)

    return {
        "config_file_loaded": str(get_config_path()),
        "mode": get_mode(),
        "alpaca_paper": paper,
        "selected_endpoint": "paper" if paper else "live",
        "live_trading_enabled_env": is_live_trading_enabled(),
        "live_trading_enabled_config": bool(cfg.get("live_trading", {}).get("enabled", False)),
        "preferred_api_key_var": preferred_key,
        "preferred_api_key_present": _present(preferred_key),
        "preferred_secret_var": preferred_secret,
        "preferred_secret_present": _present(preferred_secret),
        "fallback_api_key_var": fallback_key,
        "fallback_api_key_present": _present(fallback_key),
        "fallback_secret_var": fallback_secret,
        "fallback_secret_present": _present(fallback_secret),
        "effective_key_source": "preferred" if using_preferred else "fallback",
        "will_attempt_live_orders": get_mode() == "live" and is_live_trading_enabled(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Alpaca auth config without printing secrets.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--mode", choices=["dry_run", "paper", "live"], default=None)
    args = parser.parse_args()

    diag = collect_diagnostics(mode_override=args.mode)
    if args.json:
        print(json.dumps(diag, indent=2, sort_keys=True))
        return 0

    print("ALPACA AUTH CONFIG CHECK")
    print(f"  config_file_loaded          = {diag['config_file_loaded']}")
    print(f"  mode                        = {diag['mode']}")
    print(f"  ALPACA_PAPER                = {str(diag['alpaca_paper']).lower()}")
    print(f"  selected_endpoint           = {diag['selected_endpoint']}")
    print(f"  LIVE_TRADING enabled env    = {str(diag['live_trading_enabled_env']).lower()}")
    print(f"  live_trading.enabled config = {str(diag['live_trading_enabled_config']).lower()}")
    print(f"  preferred api key present   = {str(diag['preferred_api_key_present']).lower()} ({diag['preferred_api_key_var']})")
    print(f"  preferred secret present    = {str(diag['preferred_secret_present']).lower()} ({diag['preferred_secret_var']})")
    print(f"  fallback api key present    = {str(diag['fallback_api_key_present']).lower()} ({diag['fallback_api_key_var']})")
    print(f"  fallback secret present     = {str(diag['fallback_secret_present']).lower()} ({diag['fallback_secret_var']})")
    print(f"  effective key source        = {diag['effective_key_source']}")
    print(f"  would attempt live orders   = {str(diag['will_attempt_live_orders']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
