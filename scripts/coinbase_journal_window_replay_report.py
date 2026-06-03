#!/usr/bin/env python3
"""
scripts/coinbase_journal_window_replay_report.py — Offline journal-window OHLCV replay baseline.

Uses journal EXIT cycles + OHLCV fixtures (or real journal + covering OHLCV) to replay
the actual price path windows through the harness logic. Produces comparison of
replayed net vs journal_recorded net to validate the harness reproduces known loss
direction before any "fix" experiments.

Pure offline. No broker, no orders, no mutation, no .env.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import (
    DEFAULT_ENTRY_FEE_RATE,
    DEFAULT_EXIT_FEE_RATE,
    load_bars_from_fixture,
    parse_journal_cycles,
    run_journal_window_replay,
)

SCHEMA_VERSION = "p2-025f.coinbase_journal_window_replay_report.v1"
DEFAULT_JOURNAL = ROOT / "journal_coinbase_crypto.csv"


def _to_float(d: Any) -> float:
    if d is None:
        return 0.0
    try:
        return float(d)
    except Exception:
        return 0.0


def build_journal_window_report(
    *,
    journal_path: Optional[Path] = None,
    ohlcv_fixture: Optional[Path] = None,
    symbol: Optional[str] = None,
    max_cycles: Optional[int] = None,
    entry_fee_rate: float = float(DEFAULT_ENTRY_FEE_RATE),
    exit_fee_rate: float = float(DEFAULT_EXIT_FEE_RATE),
    fee_scenario: str = "taker/taker",
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    cycles = parse_journal_cycles(jpath)

    # filter
    if symbol:
        cycles = [c for c in cycles if c.get("symbol") == symbol]
    if max_cycles:
        cycles = cycles[:max_cycles]

    # always compute recorded aggregates
    rec_wins = rec_losses = rec_breakeven = 0
    rec_gross = rec_fees = rec_net = Decimal("0")
    rec_reasons: Dict[str, int] = defaultdict(int)
    rec_by_strat: Dict[str, Dict] = defaultdict(lambda: {"net": Decimal("0"), "count": 0})
    rec_by_sym: Dict[str, Dict] = defaultdict(lambda: {"net": Decimal("0"), "count": 0})
    for c in cycles:
        n = c.get("net_pnl_recorded", Decimal("0"))
        g = c.get("gross_pnl_recorded", Decimal("0"))
        f = c.get("fees_recorded", Decimal("0"))
        rec_gross += g
        rec_fees += f
        rec_net += n
        r = c.get("exit_reason", "unknown")
        rec_reasons[r] += 1
        strat = c.get("strategy", "unknown")
        sym = c.get("symbol", "UNKNOWN")
        rec_by_strat[strat]["net"] += n
        rec_by_strat[strat]["count"] += 1
        rec_by_sym[sym]["net"] += n
        rec_by_sym[sym]["count"] += 1
        if n > 0:
            rec_wins += 1
        elif n < 0:
            rec_losses += 1
        else:
            rec_breakeven += 1

    rec_total = len(cycles)
    rec_win_rate = round(rec_wins / rec_total, 6) if rec_total > 0 else 0.0
    rec_dominant = max(rec_reasons.items(), key=lambda x: x[1])[0] if rec_reasons else None

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "replay_class": "journal_window_offline_replay",
        "journal_path": str(jpath),
        "ohlcv_fixture": str(ohlcv_fixture) if ohlcv_fixture else None,
        "cycles_seen": rec_total,
        "trade_permission": "none",
        "risk_increase": "not_approved",
        "scaling_allowed": False,
        "notes": [
            "Offline journal-window replay baseline using actual live EXIT cycles from journal against OHLCV price paths.",
            "Replayed nets use harness fill/slippage/fee model on the window bars; recorded are from journal (broker-backed).",
            "taker/taker is conservative default. This does not approve live trading.",
            "Must reproduce journal loss direction (fee-dominated negative) before using for strategy/exit experiments.",
        ],
    }

    # recorded side (always available from journal)
    payload["journal_recorded"] = {
        "wins": rec_wins,
        "losses": rec_losses,
        "breakeven": rec_breakeven,
        "win_rate": rec_win_rate,
        "gross_pnl_sum": str(rec_gross),
        "fees_sum": str(rec_fees),
        "net_pnl_sum": str(rec_net),
        "dominant_exit_reason": rec_dominant,
        "exit_reason_breakdown": dict(rec_reasons),
        "per_strategy": {k: {"count": v["count"], "net_pnl_sum": str(v["net"])} for k, v in sorted(rec_by_strat.items())},
        "per_symbol": {k: {"count": v["count"], "net_pnl_sum": str(v["net"])} for k, v in sorted(rec_by_sym.items())},
    }

    bars = []
    if ohlcv_fixture:
        try:
            bars = load_bars_from_fixture(ohlcv_fixture)
        except Exception:
            bars = []

    replayed = run_journal_window_replay(
        bars,
        cycles,
        entry_fee_rate=entry_fee_rate,
        exit_fee_rate=exit_fee_rate,
        fee_scenario=fee_scenario,
    )

    # merge replay fields
    payload.update({
        "cycles_replayed": replayed.get("cycles_replayed", 0),
        "cycles_skipped": replayed.get("cycles_skipped", 0),
        "skip_reason_breakdown": replayed.get("skip_reason_breakdown", {}),
        "wins": replayed.get("wins", 0),
        "losses": replayed.get("losses", 0),
        "breakeven": replayed.get("breakeven", 0),
        "win_rate": replayed.get("win_rate", 0.0),
        "gross_pnl_sum": replayed.get("gross_pnl_sum", "0"),
        "fees_sum": replayed.get("fees_sum", "0"),
        "net_pnl_sum": replayed.get("net_pnl_sum", "0"),
        "journal_recorded_net_pnl_sum": replayed.get("journal_recorded_net_pnl_sum", str(rec_net)),
        "replay_vs_journal_direction_match": replayed.get("replay_vs_journal_direction_match"),
        "dominant_exit_reason": replayed.get("dominant_exit_reason"),
        "exit_reason_breakdown": replayed.get("exit_reason_breakdown", {}),
        "per_strategy": replayed.get("per_strategy", payload["journal_recorded"]["per_strategy"]),
        "per_symbol": replayed.get("per_symbol", payload["journal_recorded"]["per_symbol"]),
        "fee_scenario": replayed.get("fee_scenario", fee_scenario),
        "exit_policy": "static",  # baseline uses current static
        "per_cycle": replayed.get("per_cycle", []),
    })

    # top level safety
    payload["trade_permission"] = "none"
    payload["risk_increase"] = "not_approved"
    payload["scaling_allowed"] = False

    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Journal-window OHLCV replay baseline report (offline only)")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    ap.add_argument("--journal", type=Path, default=None, help="Path to journal csv (default journal_coinbase_crypto.csv)")
    ap.add_argument("--ohlcv-fixture", type=Path, default=None, help="Path to OHLCV json/jsonl fixture covering journal times")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--entry-fee-rate", type=float, default=float(DEFAULT_ENTRY_FEE_RATE))
    ap.add_argument("--exit-fee-rate", type=float, default=float(DEFAULT_EXIT_FEE_RATE))
    ap.add_argument("--fee-scenario", default="taker/taker", choices=["taker/taker", "maker/maker"])
    args = ap.parse_args(argv)

    payload = build_journal_window_report(
        journal_path=args.journal,
        ohlcv_fixture=args.ohlcv_fixture,
        symbol=args.symbol,
        max_cycles=args.max_cycles,
        entry_fee_rate=args.entry_fee_rate,
        exit_fee_rate=args.exit_fee_rate,
        fee_scenario=args.fee_scenario,
    )

    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
