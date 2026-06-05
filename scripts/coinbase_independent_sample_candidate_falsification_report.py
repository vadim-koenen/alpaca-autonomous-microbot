#!/usr/bin/env python3
"""
P2-026D independent-sample falsification for the fixed pre-entry candidate.

Offline diagnostic report only. It summarizes the April 2026 public OHLCV
expansion, applies the fixed P2-026B/P2-026C rule without re-optimizing, and
keeps all implementation/probe/scaling permissions false.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.coinbase_historical_signal_generator import (  # noqa: E402
    DATA_DIR,
    build_historical_signal_generator_report,
)
from scripts.coinbase_ohlcv_import_validate import _parse_ts, validate_and_normalize  # noqa: E402
from scripts.coinbase_pre_entry_candidate_holdout_validation import (  # noqa: E402
    DEFAULT_THRESHOLD,
    INPUT_FIELD,
    OPERATOR,
    RULE_NAME,
    build_holdout_validation_report,
    evaluate_candidate_result,
    _fmt_rate,
)

SCHEMA_VERSION = "p2-026d.independent_sample_candidate_falsification.v1"
REPORT_CLASS = "independent_sample_candidate_falsification"
DEFAULT_SYMBOLS = ["ADA/USD", "ALGO/USD", "BTC/USD", "ETH/USD", "SOL/USD"]
DEFAULT_START = "2026-04-01"
DEFAULT_END = "2026-04-30"


def _symbol_to_filename_prefix(symbol: str) -> str:
    return symbol.replace("/", "-")


def _coverage_for_symbol(
    *,
    data_dir: Path,
    symbol: str,
    start: str,
    end: str,
    granularity: str,
) -> Dict[str, Any]:
    path = data_dir / f"{_symbol_to_filename_prefix(symbol)}_{granularity}_{start}_{end}.csv"
    start_dt = _parse_ts(start)
    end_dt = _parse_ts(end)
    report: Dict[str, Any]
    if path.exists():
        report, _ = validate_and_normalize(
            path,
            symbol,
            start=start_dt,
            end=end_dt,
            granularity=granularity,
        )
    else:
        report = {
            "symbol": symbol,
            "input_path": str(path),
            "bar_count": 0,
            "earliest_timestamp": None,
            "latest_timestamp": None,
            "gap_count": None,
            "skipped_rows": None,
            "missing_file": True,
        }
    return {
        "symbol": symbol,
        "path": str(path),
        "exists": path.exists(),
        "rows": report.get("bar_count", 0),
        "earliest_timestamp": report.get("earliest_timestamp"),
        "latest_timestamp": report.get("latest_timestamp"),
        "gaps": report.get("gap_count"),
        "duplicates": 0,
        "malformed_rows": report.get("skipped_rows", 0),
        "coverage_quality": "gap_caveat" if report.get("gap_count", 0) else "ok",
        "algo_gap_caveat": symbol == "ALGO/USD" and bool(report.get("gap_count", 0)),
    }


def independent_data_summary(
    *,
    data_dir: Path,
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    granularity: str = "5m",
) -> Dict[str, Any]:
    rows = [
        _coverage_for_symbol(data_dir=data_dir, symbol=symbol, start=start, end=end, granularity=granularity)
        for symbol in symbols
    ]
    return {
        "symbols": list(symbols),
        "date_ranges": [{"start": start, "end": end, "granularity": granularity}],
        "rows": {row["symbol"]: row["rows"] for row in rows},
        "gaps": {row["symbol"]: row["gaps"] for row in rows},
        "duplicates": {row["symbol"]: row["duplicates"] for row in rows},
        "malformed_rows": {row["symbol"]: row["malformed_rows"] for row in rows},
        "files": rows,
        "all_files_present": all(row["exists"] for row in rows),
        "data_dir": str(data_dir),
        "data_offline_ohlcv_untracked_expected": True,
    }


def _independent_window_cycles(cycles: Sequence[Dict[str, Any]], start: str, end: str) -> List[Dict[str, Any]]:
    marker = f"{start}_{end}"
    return [cycle for cycle in cycles if marker in str(cycle.get("source_ohlcv_file", ""))]


def _source_summary(source_payload: Dict[str, Any], holdout_payload: Dict[str, Any]) -> Dict[str, Any]:
    source = holdout_payload["source_synthetic_summary"]
    return {
        "bars_scanned": source.get("bars_scanned"),
        "synthetic_cycles_count": source.get("synthetic_cycles_count"),
        "baseline_gross": source.get("baseline_gross"),
        "baseline_win_rate": source.get("baseline_win_rate"),
        "baseline_stop_loss_count": source.get("baseline_stop_loss_count"),
        "leakage_guards": source.get("leakage_guards"),
        "data_dir": source_payload.get("data_dir"),
    }


def _prior_result_summary() -> Dict[str, Any]:
    return {
        "p2_026b_same_sample_result": {
            "hypotheses_evaluated": 172,
            "validated_candidates": 1,
            "provisional_candidates": 8,
            "best_candidate": RULE_NAME,
            "best_candidate_status": "validated_candidate",
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "p2_026c_holdout_verdict": {
            "verdict": "unstable_or_overfit",
            "holdout_validated": False,
            "provisionally_stable": False,
            "likely_overfit": True,
            "implementation_proposal_authorized": False,
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
            "failed_reasons": [
                "chronological holdout failed gate",
                "filtered holdout sample_size_after=17",
                "avg_gross_after=-0.00004180",
                "win_rate_after=0.470588",
                "evidence depended on one strategy",
            ],
        },
    }


def _verdict(
    *,
    expanded: Dict[str, Any],
    independent: Dict[str, Any],
    holdout: Dict[str, Any],
    checks: Dict[str, Any],
) -> Dict[str, Any]:
    expanded_pass = bool(expanded.get("passes_gate"))
    independent_pass = bool(independent.get("passes_gate"))
    holdout_pass = bool(holdout.get("passes_gate"))
    depends_on_one_strategy = bool(checks.get("depends_on_one_strategy"))
    threshold_robust = bool(checks.get("threshold_robust"))
    independently_validated = (
        expanded_pass
        and independent_pass
        and holdout_pass
        and not depends_on_one_strategy
        and threshold_robust
    )
    falsified = not expanded_pass and not independent_pass
    provisionally_stable = (
        not independently_validated
        and expanded_pass
        and independent_pass
        and not holdout_pass
        and threshold_robust
    )
    if independently_validated:
        verdict = "independently_validated"
    elif falsified:
        verdict = "falsified"
    elif provisionally_stable:
        verdict = "provisionally_stable_needs_more_data"
    else:
        verdict = "still_unstable"
    return {
        "verdict": verdict,
        "independently_validated": independently_validated,
        "falsified": falsified,
        "likely_overfit": not independently_validated,
        "implementation_proposal_authorized": False,
        "implementation_authorized": False,
        "paper_probe_authorized": False,
        "live_probe_authorized": False,
        "scaling_authorized": False,
    }


def build_independent_sample_falsification_report(
    *,
    data_dir: Optional[Path] = None,
    independent_start: str = DEFAULT_START,
    independent_end: str = DEFAULT_END,
    granularity: str = "5m",
    max_bars: Optional[int] = 100000,
    max_cycles: Optional[int] = 2000,
    source_payload: Optional[Dict[str, Any]] = None,
    synthetic_cycles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    dpath = data_dir or DATA_DIR
    if source_payload is None:
        source_payload = build_historical_signal_generator_report(
            data_dir=dpath,
            max_bars=max_bars,
            max_cycles=max_cycles,
        )
    cycles = list(synthetic_cycles if synthetic_cycles is not None else source_payload.get("synthetic_cycles", []))
    holdout_payload = build_holdout_validation_report(
        data_dir=dpath,
        threshold=DEFAULT_THRESHOLD,
        max_bars=max_bars,
        max_cycles=max_cycles,
        source_payload=source_payload,
        synthetic_cycles=cycles,
    )
    independent_cycles = _independent_window_cycles(cycles, independent_start, independent_end)
    independent_result = evaluate_candidate_result(
        label=f"independent_window_{independent_start}_{independent_end}",
        cycles=independent_cycles,
        threshold=DEFAULT_THRESHOLD,
    )
    expanded_result = holdout_payload["full_sample_result"]
    holdout_result = holdout_payload["chronological_holdout_result"]
    checks = holdout_payload["stability_checks"]
    verdict = _verdict(
        expanded=expanded_result,
        independent=independent_result,
        holdout=holdout_result,
        checks=checks,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "report_class": REPORT_CLASS,
        "candidate": {
            "rule_name": RULE_NAME,
            "input_field": INPUT_FIELD,
            "operator": OPERATOR,
            "threshold": _fmt_rate(DEFAULT_THRESHOLD),
            "pre_entry_only": True,
            "leakage_risk": False,
        },
        "prior_result_summary": _prior_result_summary(),
        "independent_data_summary": independent_data_summary(
            data_dir=dpath,
            symbols=DEFAULT_SYMBOLS,
            start=independent_start,
            end=independent_end,
            granularity=granularity,
        ),
        "expanded_synthetic_summary": _source_summary(source_payload, holdout_payload),
        "candidate_expanded_result": expanded_result,
        "independent_window_result": independent_result,
        "chronological_holdout_result": holdout_result,
        "rolling_fold_results": holdout_payload["rolling_fold_results"],
        "symbol_stability": holdout_payload["symbol_stability"],
        "strategy_stability": holdout_payload["strategy_stability"],
        "threshold_sensitivity": holdout_payload["threshold_sensitivity"],
        "falsification_verdict": verdict,
        "limitations": [
            "April 2026 files are local untracked offline OHLCV working data.",
            "ALGO/USD April coverage has gap caveats.",
            "Synthetic cycles are not live fills.",
            "The fixed rule still uses gross synthetic outcomes for evaluation only.",
            "No live strategy filter, paper probe, live probe, or scaling is authorized.",
        ],
        "next_step_recommendation": (
            "Treat the P2-026B candidate as falsified/still unstable unless future independent samples reverse this result. "
            "Pivot toward offline strategy redesign or broader independent-sample falsification before any implementation proposal."
        ),
    }


def write_report(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _human_summary(payload: Dict[str, Any]) -> str:
    source = payload["expanded_synthetic_summary"]
    expanded = payload["candidate_expanded_result"]
    independent = payload["independent_window_result"]
    holdout = payload["chronological_holdout_result"]
    verdict = payload["falsification_verdict"]
    lines = [
        "=== P2-026D INDEPENDENT SAMPLE CANDIDATE FALSIFICATION ===",
        f"rule_name={payload['candidate']['rule_name']}",
        f"threshold={payload['candidate']['threshold']}",
        f"bars_scanned={source['bars_scanned']}",
        f"synthetic_cycles_count={source['synthetic_cycles_count']}",
        f"baseline_gross={source['baseline_gross']} win_rate={source['baseline_win_rate']}",
        "",
        f"candidate_expanded_passes_gate={str(expanded['passes_gate']).lower()} gross_delta={expanded['gross_delta']}",
        f"independent_window_passes_gate={str(independent['passes_gate']).lower()} gross_delta={independent['gross_delta']}",
        f"chronological_holdout_passes_gate={str(holdout['passes_gate']).lower()} gross_delta={holdout['gross_delta']}",
        "",
        f"verdict={verdict['verdict']}",
        f"independently_validated={str(verdict['independently_validated']).lower()}",
        f"falsified={str(verdict['falsified']).lower()}",
        f"likely_overfit={str(verdict['likely_overfit']).lower()}",
        "Permission verdict: implementation=false paper=false live=false scaling=false",
        f"Next: {payload['next_step_recommendation']}",
        "=== END REPORT ===",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P2-026D independent-sample candidate falsification")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--independent-start", default=DEFAULT_START)
    parser.add_argument("--independent-end", default=DEFAULT_END)
    parser.add_argument("--granularity", default="5m")
    parser.add_argument("--max-bars", type=int, default=100000)
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output; no write by default")
    args = parser.parse_args(argv)

    payload = build_independent_sample_falsification_report(
        data_dir=args.data_dir,
        independent_start=args.independent_start,
        independent_end=args.independent_end,
        granularity=args.granularity,
        max_bars=args.max_bars,
        max_cycles=args.max_cycles,
    )
    if args.output:
        write_report(args.output, payload)
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(_human_summary(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
