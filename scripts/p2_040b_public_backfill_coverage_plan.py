#!/usr/bin/env python3
"""P2-040B Public Backfill Readiness / Coverage Plan Generator.

Generates a precise coverage plan for public OHLCV backfill without
fetching data. Evaluates existing local manifests and produces the
required future commands for the P2-040A approval runner.
"""

import argparse
import datetime
import json
import logging
import math
import pathlib
import sys
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# P2-040A approval defaults
REQUIRED_APPROVAL_TOKEN = "PUBLIC_BACKFILL_APPROVED"
RUNNER_SCRIPT = "scripts/p2_040a_public_backfill_approval_runner.py"

def normalize_symbol(symbol: str) -> str:
    """Normalize symbol for filesystem paths."""
    return symbol.replace("/", "_").replace("-", "_").upper()

def estimate_bars(start: datetime.datetime, end: datetime.datetime, timeframe: str) -> int:
    """Estimate the number of expected bars based on time delta."""
    delta = end - start
    if timeframe == "1m":
        return max(0, int(delta.total_seconds() // 60))
    elif timeframe == "5m":
        return max(0, int(delta.total_seconds() // 300))
    elif timeframe == "1h":
        return max(0, int(delta.total_seconds() // 3600))
    elif timeframe == "1d":
        return max(0, int(delta.total_seconds() // 86400))
    return max(0, int(delta.total_seconds() // 60)) # default 1m fallback

def build_future_command(provider: str, symbol: str, timeframe: str, start: datetime.datetime, end: datetime.datetime, output_root: pathlib.Path) -> str:
    """Build the informational future command for P2-040A."""
    cmd = (
        f"python3 {RUNNER_SCRIPT} \\\n"
        f"  --provider {provider} \\\n"
        f"  --symbol {symbol} \\\n"
        f"  --timeframe {timeframe} \\\n"
        f"  --start {start.isoformat().replace('+00:00', 'Z')} \\\n"
        f"  --end {end.isoformat().replace('+00:00', 'Z')} \\\n"
        f"  --output-root {output_root} \\\n"
        f"  --allow-public-fetch \\\n"
        f"  --approval-token {REQUIRED_APPROVAL_TOKEN}"
    )
    return cmd

def scan_existing_coverage(output_location: pathlib.Path) -> int:
    """Read existing row counts from manifest JSON files safely."""
    total_bars = 0
    if output_location.exists() and output_location.is_dir():
        for manifest_path in output_location.glob("*.manifest.json"):
            try:
                with open(manifest_path, "r") as f:
                    data = json.load(f)
                    total_bars += data.get("row_count", 0)
            except Exception as e:
                logging.warning(f"Failed to read manifest {manifest_path}: {e}")
    return total_bars

def chunk_date_range(start: datetime.datetime, end: datetime.datetime, chunk_days: int) -> List[tuple[datetime.datetime, datetime.datetime]]:
    """Break a date range into chunk_days sized pieces."""
    chunks = []
    current = start
    while current < end:
        chunk_end = min(end, current + datetime.timedelta(days=chunk_days))
        chunks.append((current, chunk_end))
        current = chunk_end
    return chunks

def build_coverage_plan(
    provider: str,
    symbols: List[str],
    timeframe: str,
    days: int,
    end_dt: datetime.datetime,
    output_root: pathlib.Path,
    chunk_days: int | None = None,
    max_bars_per_request: int | None = None,
) -> Dict[str, Any]:
    
    start_dt = end_dt - datetime.timedelta(days=days)
    
    plan = {
        "plan_only": True,
        "public_fetch_performed": False,
        "provider": provider,
        "symbols": symbols,
        "timeframe": timeframe,
        "requested_days": days,
        "start": start_dt.isoformat().replace('+00:00', 'Z'),
        "end": end_dt.isoformat().replace('+00:00', 'Z'),
        "expected_bars_total": 0,
        "plans_by_symbol": [],
        "existing_coverage_summary": 0,
        "coverage_gap_summary": 0,
        "future_approval_required": True,
        "approval_token_required": True,
        "approval_token_value": REQUIRED_APPROVAL_TOKEN,
        "future_runner_script": RUNNER_SCRIPT,
        "future_commands": [],
        "ml_blocked_until_replay_grade_coverage": True,
        "economic_baseline": "NET_PNL≈-$1.58 across 80 historical trades"
    }
    
    for symbol in symbols:
        sym_norm = normalize_symbol(symbol)
        expected_output_location = output_root / sym_norm / timeframe
        
        expected_bars = estimate_bars(start_dt, end_dt, timeframe)
        existing_bars = scan_existing_coverage(expected_output_location)
        
        missing_bars = max(0, expected_bars - existing_bars)
        coverage_pct = round((existing_bars / expected_bars * 100.0), 2) if expected_bars > 0 else 0.0
        
        sym_plan = {
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start_dt.isoformat().replace('+00:00', 'Z'),
            "end": end_dt.isoformat().replace('+00:00', 'Z'),
            "expected_bars": expected_bars,
            "output_root": str(output_root),
            "expected_output_location": str(expected_output_location),
            "existing_bars": existing_bars,
            "missing_bars_estimate": missing_bars,
            "coverage_percent_estimate": coverage_pct,
            "chunks": [],
            "future_commands": []
        }
        
        # Build Chunks
        ranges = []
        if chunk_days:
            ranges = chunk_date_range(start_dt, end_dt, chunk_days)
        else:
            ranges = [(start_dt, end_dt)]
            
        for c_start, c_end in ranges:
            c_expected = estimate_bars(c_start, c_end, timeframe)
            cmd = build_future_command(provider, symbol, timeframe, c_start, c_end, output_root)
            
            sym_plan["chunks"].append({
                "symbol": symbol,
                "timeframe": timeframe,
                "chunk_start": c_start.isoformat().replace('+00:00', 'Z'),
                "chunk_end": c_end.isoformat().replace('+00:00', 'Z'),
                "expected_bars": c_expected,
                "future_command": cmd
            })
            sym_plan["future_commands"].append(cmd)
            plan["future_commands"].append(cmd)
            
        plan["plans_by_symbol"].append(sym_plan)
        plan["expected_bars_total"] += expected_bars
        plan["existing_coverage_summary"] += existing_bars
        plan["coverage_gap_summary"] += missing_bars
        
    return plan

def main():
    parser = argparse.ArgumentParser(
        description="P2-040B Public Backfill Readiness / Coverage Plan Generator"
    )
    
    parser.add_argument("--provider", default="coinbase_public", help="Data provider (e.g. coinbase_public)")
    parser.add_argument("--symbols", default="BTC/USD", help="Comma-separated symbols")
    parser.add_argument("--timeframe", default="1m", help="Timeframe (e.g. 1m)")
    parser.add_argument("--days", type=int, default=90, help="Number of days to plan backwards")
    parser.add_argument("--end", type=str, default=None, help="End datetime ISO8601 (default: now UTC)")
    parser.add_argument("--output-root", type=str, default=None, help="Root path for market data substrate")
    parser.add_argument("--report-json", type=str, default=None, help="Output path for machine-readable JSON plan")
    parser.add_argument("--max-bars-per-request", type=int, default=None, help="Provider planning constraint")
    parser.add_argument("--chunk-days", type=int, default=None, help="Chunk size in days for future fetch commands")
    
    args = parser.parse_args()
    
    # Parse dates
    if args.end:
        end_dt = datetime.datetime.fromisoformat(args.end.replace('Z', '+00:00'))
    else:
        end_dt = datetime.datetime.now(datetime.timezone.utc)
        
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)
        
    symbols = [s.strip() for s in args.symbols.split(",")]
    
    if args.output_root:
        out_root = pathlib.Path(args.output_root)
    else:
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        out_root = repo_root / "data" / "market_data" / "ohlcv"
        
    plan = build_coverage_plan(
        provider=args.provider,
        symbols=symbols,
        timeframe=args.timeframe,
        days=args.days,
        end_dt=end_dt,
        output_root=out_root,
        chunk_days=args.chunk_days,
        max_bars_per_request=args.max_bars_per_request
    )
    
    # Output to console
    print("=== P2-040B COVERAGE PLAN ===")
    print(json.dumps(plan, indent=2))
    
    if args.report_json:
        rpath = pathlib.Path(args.report_json)
        rpath.parent.mkdir(parents=True, exist_ok=True)
        with open(rpath, "w") as f:
            json.dump(plan, f, indent=2)
        logging.info(f"Report written to {rpath}")
        
    logging.info("SAFETY: This is a read-only plan. No public fetch performed.")
    logging.info("SAFETY: Future commands listed in this plan require separate explicit user approval.")

if __name__ == "__main__":
    main()
