#!/usr/bin/env python3
"""Advisory report for Shadow Learner Prediction Derivative Features."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.prediction_features import assemble_symbol_features, get_brier_metrics
from shadow_learner.scoring_reconciliation import ScoringReconciler
from shadow_learner.schema import connect, init_db


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_markdown_report(since: str | None, symbol_filter: str | None, db_path: str | None) -> str:
    init_db(db_path)
    
    # 1. Available Symbols and Coverage
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, COUNT(*) as count, MIN(timestamp_utc) as first, MAX(timestamp_utc) as last "
            "FROM shadow_price_points GROUP BY symbol ORDER BY symbol"
        ).fetchall()
        coverage = [dict(r) for r in rows]

    lines = [
        "# Shadow Learner Prediction Feature Report",
        "",
        "> **ADVISORY ONLY**: This report calculates derived market features from shadow-mode "
        "data. These metrics are for research only and have **NO LIVE TRADING INFLUENCE**.",
        "",
        "## Price Point Coverage",
        "| Symbol | Points | First Seen | Last Seen |",
        "|---|---:|---|---|",
    ]
    
    for c in coverage:
        lines.append(f"| {c['symbol']} | {c['count']} | {c['first']} | {c['last']} |")
    
    lines.append("")
    
    # 2. Derivative Feature Examples
    lines.append("## Derivative Feature Examples (Latest Available T0)")
    lines.append("| Symbol | T0 | Price | Ret 1m | Ret 15m | Velocity 15m | Vol 15m | Win Rate |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    
    target_symbols = [symbol_filter] if symbol_filter else [c["symbol"] for c in coverage]
    
    for sym in target_symbols:
        # Use last seen timestamp as T0 for examples
        sym_coverage = next((c for c in coverage if c["symbol"] == sym), None)
        if not sym_coverage or not sym_coverage["last"]:
            lines.append(f"| {sym} | n/a | ERROR | no_data | | | | |")
            continue
            
        t0 = _parse_utc(sym_coverage["last"])
        features = assemble_symbol_features(sym, t0, db_path=db_path)
        if "error" in features:
            lines.append(f"| {sym} | {sym_coverage['last']} | ERROR | {features['error']} | | | | |")
        else:
            lines.append(
                f"| {sym} | {sym_coverage['last']} | {_fmt(features['price_t0'])} | "
                f"{_fmt(features['return_1m'])} | {_fmt(features['return_15m'])} | "
                f"{_fmt(features['price_velocity_15m'])} | {_fmt(features['volatility_15m'])} | "
                f"{_fmt(features.get('recent_win_rate_by_symbol'))} |"
            )
            
    lines.append("")
    
    # 3. Scoring Reconciliation Watch Buckets
    lines.append("## Current Scoring Watch Buckets")
    reconciler = ScoringReconciler(db_path=db_path)
    recon = reconciler.reconcile(since=since)
    
    if recon["watchlist"]:
        lines.append("| Model | Symbol | Horizon | Samples | Acc Delta | Brier Delta |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for b in recon["watchlist"]:
            lines.append(
                f"| {b['model']} | {b['symbol']} | {b['horizon']}m | {b['sample_count']} | "
                f"{_fmt(b['accuracy_delta'])} | {_fmt(b['brier_delta'])} |"
            )
    else:
        lines.append("No buckets currently in watchlist.")
        
    lines.append("")
    
    # 4. BTC/ETH/SOL Readiness
    lines.append("## BTC/ETH/SOL Evaluation Readiness")
    core_crypto = ["BTC/USD", "ETH/USD", "SOL/USD"]
    lines.append("| Symbol | Status | Points | Samples | Recommendation |")
    lines.append("|---|---|---:|---:|---|")
    
    msh_metrics = recon["diag_report"].get("msh_metrics", {})
    
    for sym in core_crypto:
        count = next((c["count"] for c in coverage if c["symbol"] == sym), 0)
        samples = sum(m["sample_count"] for k, m in msh_metrics.items() if k[1] == sym)
        
        status = "READY" if count > 500 and samples > 20 else "COLLECTING"
        rec = "Ready for evaluation" if status == "READY" else "Requires more exploration data"
        lines.append(f"| {sym} | {status} | {count} | {samples} | {rec} |")
        
    lines.extend([
        "",
        "## Feature Coverage and Missing Data",
        "- **Spread Trend**: Currently placeholders; requires deeper join with snapshots.",
        "- **Volume Trend**: Currently limited by Coinbase 1m bar volume consistency.",
        "- **Brier Score**: Calculated per bucket where labeled outcomes exist.",
        "",
        "---",
        f"Report generated at {datetime.now(timezone.utc).isoformat()}",
    ])
    
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", help="UTC date or timestamp lower bound")
    parser.add_argument("--symbol", help="Optional symbol filter")
    parser.add_argument("--output", help="Optional markdown report output path")
    parser.add_argument("--db", help="Optional shadow learner SQLite path")
    args = parser.parse_args()

    report_md = redact_text(build_markdown_report(args.since, args.symbol, args.db))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_md + "\n", encoding="utf-8")
        print(redact_text(f"Wrote prediction feature report: {output_path}"))
    else:
        print(report_md)

    return 0


if __name__ == "__main__":
    sys.exit(main())
