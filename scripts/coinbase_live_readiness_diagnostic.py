#!/usr/bin/env python3
"""
P2-016B — Coinbase Live Readiness Diagnostic (read-only, zero broker calls by default).

Purpose:
Help the operator determine whether a live-read-only broker truth check is likely to succeed
before running the full probe with --live-read-only.

Safety guarantees:
- Default mode makes ZERO network or broker API calls.
- Never prints secret values (only boolean presence).
- Does not load .env unless the existing repo convention already does so for this purpose.
- Does not instantiate BrokerCoinbase in a way that triggers network calls.
- Uses static signature inspection where possible.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Make runnable from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _safe_get_env_presence(key: str) -> bool:
    """Return True only if the environment variable is present and non-empty (redacted)."""
    val = os.environ.get(key)
    return bool(val and val.strip())


def _get_coinbase_key_presence() -> Dict[str, bool]:
    """Check for common Coinbase Advanced Trade credential environment variables."""
    return {
        "has_coinbase_api_key": _safe_get_env_presence("COINBASE_API_KEY"),
        "has_coinbase_api_secret": _safe_get_env_presence("COINBASE_API_SECRET"),
        # Passphrase is not typically required for the current Advanced Trade REST client,
        # but we report it for completeness if someone is using a different flow.
        "has_coinbase_passphrase": _safe_get_env_presence("COINBASE_PASSPHRASE"),
    }


def _inspect_broker_constructor() -> Dict[str, Any]:
    """Safely inspect the BrokerCoinbase constructor signature without instantiating it."""
    result: Dict[str, Any] = {
        "coinbase_client_importable": False,
        "broker_coinbase_importable": False,
        "broker_constructor_signature": None,
        "broker_constructor_accepts_dry_run": None,
        "error": None,
    }

    try:
        from coinbase.rest import RESTClient  # type: ignore
        result["coinbase_client_importable"] = True
    except Exception as e:
        result["error"] = f"coinbase.rest import failed: {e}"
        return result

    try:
        from broker_coinbase import BrokerCoinbase  # type: ignore
        result["broker_coinbase_importable"] = True

        sig = inspect.signature(BrokerCoinbase.__init__)
        result["broker_constructor_signature"] = str(sig)

        params = list(sig.parameters.keys())
        result["broker_constructor_accepts_dry_run"] = "dry_run" in params

    except Exception as e:
        result["error"] = f"BrokerCoinbase import/inspection failed: {e}"

    return result


def _check_live_probe_script() -> bool:
    probe_path = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_live_broker_reconciliation_probe.py"
    return probe_path.exists()


def build_readiness_report() -> Dict[str, Any]:
    """Build a complete, redacted readiness report. Never makes network calls."""
    key_presence = _get_coinbase_key_presence()
    broker_info = _inspect_broker_constructor()
    probe_exists = _check_live_probe_script()

    has_minimal_keys = key_presence["has_coinbase_api_key"] and key_presence["has_coinbase_api_secret"]

    if not broker_info["broker_coinbase_importable"]:
        verdict = "BLOCKED"
        recommended = "BrokerCoinbase class cannot be imported. Check installation and Python path."
    elif not has_minimal_keys:
        verdict = "BLOCKED"
        recommended = "Missing COINBASE_API_KEY or COINBASE_API_SECRET in environment. Add them (read-only) and re-run."
    elif not broker_info.get("broker_constructor_accepts_dry_run", True):
        # We now know the constructor does not accept dry_run (from P2-015B)
        verdict = "READY_WITH_CAUTION"
        recommended = "Credentials appear present. The probe no longer passes dry_run=. Use --live-read-only when ready. Consider running with a very small scope first."
    else:
        verdict = "READY"
        recommended = "Credentials appear present and adapter looks compatible. You may now run the live probe with --live-read-only --json."

    return {
        "verdict": verdict,
        "network_calls_made": False,
        "broker_calls_made": False,
        "has_coinbase_api_key": key_presence["has_coinbase_api_key"],
        "has_coinbase_api_secret": key_presence["has_coinbase_api_secret"],
        "has_coinbase_passphrase": key_presence["has_coinbase_passphrase"],
        "coinbase_client_importable": broker_info["coinbase_client_importable"],
        "broker_coinbase_importable": broker_info["broker_coinbase_importable"],
        "broker_constructor_signature": broker_info.get("broker_constructor_signature"),
        "broker_constructor_accepts_dry_run": broker_info.get("broker_constructor_accepts_dry_run"),
        "live_probe_script_exists": probe_exists,
        "recommended_next_action": recommended,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "This diagnostic makes zero network or broker API calls by default. It only inspects environment variables and Python object signatures.",
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2-016B Coinbase Live Readiness Diagnostic — zero network calls by default"
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    report = build_readiness_report()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Live Readiness Diagnostic (P2-016B) ===")
        print(f"Verdict: {report['verdict']}")
        print()
        print("Credential presence (redacted):")
        print(f"  COINBASE_API_KEY present:    {report['has_coinbase_api_key']}")
        print(f"  COINBASE_API_SECRET present: {report['has_coinbase_api_secret']}")
        print(f"  COINBASE_PASSPHRASE present: {report['has_coinbase_passphrase']}")
        print()
        print("Adapter / client status:")
        print(f"  coinbase.rest importable:    {report['coinbase_client_importable']}")
        print(f"  BrokerCoinbase importable:   {report['broker_coinbase_importable']}")
        print(f"  Constructor signature:       {report['broker_constructor_signature']}")
        print(f"  Accepts dry_run= (legacy):   {report['broker_constructor_accepts_dry_run']}")
        print()
        print(f"Live probe script present:     {report['live_probe_script_exists']}")
        print()
        print(f"Recommended next action:\n  {report['recommended_next_action']}")
        print()
        print("Note: This run made zero network or broker API calls.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())