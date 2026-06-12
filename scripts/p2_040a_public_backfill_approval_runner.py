#!/usr/bin/env python3
"""P2-040A Narrow Public Backfill Approval Runner.

Governed approval-runner layer around the P2-039D public OHLCV backfill adapter.
Adds a mandatory approval-token gate on top of the existing --allow-public-fetch
flag, making accidental real public fetches impossible.

SAFETY DEFAULTS:
- Dry-run / plan-only by default.
- Real public fetch requires BOTH --allow-public-fetch AND
  --approval-token PUBLIC_BACKFILL_APPROVED.
- NO authenticated broker, account, or order access.
- NO ML until replay-grade coverage exists.
- NET_PNL approx -$1.58 across 80 historical trades.
"""

import argparse
import datetime
import json
import logging
import pathlib
import sys
from typing import Dict, Any

import pandas as pd

# Import P2-039D adapter
try:
    from scripts import p2_039d_public_ohlcv_backfill_adapter as adapter
except ImportError:
    import p2_039d_public_ohlcv_backfill_adapter as adapter

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

REQUIRED_APPROVAL_TOKEN = "PUBLIC_BACKFILL_APPROVED"


def build_plan(
    provider: str,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    output_root: str,
    allow_public_fetch: bool,
    approval_token: str | None,
    dry_run: bool,
) -> Dict[str, Any]:
    """Build a backfill plan/report dict without executing any fetch."""

    plan = {
        "provider": provider,
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start,
        "end": end,
        "output_root": output_root,
        "dry_run": dry_run,
        "public_fetch_requested": allow_public_fetch,
        "public_fetch_performed": False,
        "generated_data_written": False,
        "blocked_reason": None,
    }

    if dry_run:
        plan["blocked_reason"] = "dry_run: plan-only mode"
        return plan

    if not allow_public_fetch:
        plan["blocked_reason"] = "public fetch not requested (missing --allow-public-fetch)"
        return plan

    if approval_token != REQUIRED_APPROVAL_TOKEN:
        plan["blocked_reason"] = (
            f"approval token missing or invalid (expected --approval-token {REQUIRED_APPROVAL_TOKEN})"
        )
        return plan

    # All gates passed — plan is approved for execution
    return plan


def run_approved_fetch(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the approved fetch via the P2-039D adapter.

    Only called when all gates pass. Returns an updated plan dict.
    """
    start_dt = pd.to_datetime(plan["start"], utc=True).to_pydatetime()
    end_dt = pd.to_datetime(plan["end"], utc=True).to_pydatetime()
    out_root = pathlib.Path(plan["output_root"])

    result = adapter.prepare_and_fetch(
        provider_name=plan["provider"],
        symbol=plan["symbol"],
        timeframe=plan["timeframe"],
        start_dt=start_dt,
        end_dt=end_dt,
        allow_public_fetch=True,
        output_root=out_root,
        use_mock=True,  # Always mock in current implementation
    )

    plan["public_fetch_performed"] = result.get("public_fetch_performed", False)
    plan["generated_data_written"] = result.get("out_path") is not None
    if "coverage" in result:
        plan["coverage"] = result["coverage"]
    if "out_path" in result:
        plan["out_path"] = result["out_path"]

    return plan


def execute(
    provider: str,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    output_root: str,
    allow_public_fetch: bool = False,
    approval_token: str | None = None,
    dry_run: bool = True,
    report_json_path: str | None = None,
) -> Dict[str, Any]:
    """Main entry point for the approval runner."""

    plan = build_plan(
        provider=provider,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        output_root=output_root,
        allow_public_fetch=allow_public_fetch,
        approval_token=approval_token,
        dry_run=dry_run,
    )

    # Log the plan
    logging.info("=== P2-040A BACKFILL APPROVAL RUNNER ===")
    for k, v in plan.items():
        logging.info(f"  {k}: {v}")

    # Execute only if no blocked_reason
    if plan["blocked_reason"] is None:
        logging.info("All approval gates passed. Delegating to P2-039D adapter.")
        plan = run_approved_fetch(plan)
    else:
        logging.info(f"BLOCKED: {plan['blocked_reason']}")

    # Write JSON report if requested
    if report_json_path:
        rpath = pathlib.Path(report_json_path)
        rpath.parent.mkdir(parents=True, exist_ok=True)
        with open(rpath, "w") as f:
            json.dump(plan, f, indent=2, default=str)
        logging.info(f"Report written to {rpath}")

    return plan


def main():
    parser = argparse.ArgumentParser(
        description=(
            "P2-040A Narrow Public Backfill Approval Runner\n\n"
            "SAFETY DEFAULTS:\n"
            "- Dry-run / plan-only by default.\n"
            "- Real public fetch requires BOTH --allow-public-fetch AND\n"
            "  --approval-token PUBLIC_BACKFILL_APPROVED.\n"
            "- NO authenticated broker, account, or order access.\n"
            "- NO ML until replay-grade coverage exists.\n"
            "- Current economic baseline: NET_PNL ≈ -$1.58 across 80 trades."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument("--provider", required=True, help="Public data provider name")
    parser.add_argument("--symbol", required=True, help="Symbol (e.g. BTC/USD)")
    parser.add_argument("--timeframe", default="1m", help="Timeframe (default: 1m)")
    parser.add_argument("--start", required=True, help="Start datetime ISO8601")
    parser.add_argument("--end", required=True, help="End datetime ISO8601")
    parser.add_argument("--output-root", default=None, help="Output root directory")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Plan-only mode (default: true)")
    parser.add_argument("--allow-public-fetch", action="store_true",
                        help="Explicitly request public network fetch")
    parser.add_argument("--approval-token", default=None,
                        help="Approval token (required: PUBLIC_BACKFILL_APPROVED)")
    parser.add_argument("--report-json", default=None,
                        help="Path to write JSON report")

    args = parser.parse_args()

    # Resolve output root
    if args.output_root:
        out_root = args.output_root
    else:
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        out_root = str(repo_root / "data" / "market_data" / "ohlcv")

    # If --allow-public-fetch is set, disable dry_run for the gate logic
    effective_dry_run = not args.allow_public_fetch

    result = execute(
        provider=args.provider,
        symbol=args.symbol,
        timeframe=args.timeframe,
        start=args.start,
        end=args.end,
        output_root=out_root,
        allow_public_fetch=args.allow_public_fetch,
        approval_token=args.approval_token,
        dry_run=effective_dry_run,
        report_json_path=args.report_json,
    )

    # Exit nonzero when public fetch was requested but blocked
    if result["public_fetch_requested"] and result["blocked_reason"] is not None:
        logging.error(f"Public fetch BLOCKED: {result['blocked_reason']}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
