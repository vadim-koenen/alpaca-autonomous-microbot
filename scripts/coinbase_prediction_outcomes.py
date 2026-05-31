#!/usr/bin/env python3
"""
P2-013A — Read-only Prediction Outcome Evaluator + Trade Attribution CLI.

Usage (offline, no network):
    python3 scripts/coinbase_prediction_outcomes.py
    python3 scripts/coinbase_prediction_outcomes.py --json
    python3 scripts/coinbase_prediction_outcomes.py --telemetry logs/prediction_telemetry.jsonl

Always read-only. Never writes to fill logger or places orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prediction_telemetry import PredictionOutcomeEvaluator, load_prediction_telemetry_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="P2-013A Prediction Outcome Evaluator (read-only)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--telemetry", type=str, default=None, help="Path to prediction_telemetry.jsonl")
    parser.add_argument("--journal", type=str, default=None, help="Path to journal CSV (optional for attribution)")
    args = parser.parse_args()

    evaluator = PredictionOutcomeEvaluator()
    tpath = Path(args.telemetry) if args.telemetry else None
    jpath = Path(args.journal) if args.journal else None

    result = evaluator.run_evaluation(telemetry_path=tpath, journal_path=jpath)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    print("=== P2-013B Prediction Outcome Evaluation + Attribution (read-only) ===")
    summary = result.get("summary", {})
    print(f"Total evaluated outcomes: {summary.get('total_evaluated_outcomes', 0)}")
    print(f"Evaluable horizons: {summary.get('evaluable_horizon_count', 0)} | no_price_data: {summary.get('no_price_data_count', 0)}")
    print(f"Candidate-to-trade conversions: {summary.get('candidate_to_trade_count', 0)}")
    print(f"Unmatched telemetry candidates: {summary.get('unmatched_telemetry_candidates', 0)}")
    print(f"Unmatched journal trades: {summary.get('unmatched_journal_trades', 0)}")
    print()
    print("Hit rate by symbol (None = insufficient future price data for those proposals):")
    for s, hr in summary.get("hit_rate_by_symbol", {}).items():
        print(f"  {s}: {hr}")
    print()
    print("Conversions by symbol:", summary.get("conversions_by_symbol", {}))
    print("Conversions by strategy:", summary.get("conversions_by_strategy", {}))
    print()
    print("Skipped reason counts:")
    for reason, cnt in summary.get("skipped_reasons", {}).items():
        print(f"  {reason}: {cnt}")
    print()
    print("P&L attribution by symbol (where exits matched):")
    for s, pnl in summary.get("pnl_usd_by_symbol", {}).items():
        print(f"  {s}: ${pnl:.2f}")
    print()
    print("Data quality note: Hit rates are None when no local candle data (data/manual_prices/) covers the proposal timestamps + horizons.")
    print("Unmatched candidates/trades are reported above for diagnosis. This run is 100% read-only.")
    print("See docs/PREDICTION_OUTCOME_EVALUATION.md for interpretation.")


if __name__ == "__main__":
    main()
