#!/usr/bin/env python3
"""
scripts/coinbase_offline_backtest_report.py — CLI for offline backtest/replay.

Offline/fixture only. Emits JSON with trade_permission=none, risk_increase=not_approved, scaling_allowed=false.
No broker calls, no orders, no runtime mutation.

Usage examples:
  python3 scripts/coinbase_offline_backtest_report.py --json
  python3 scripts/coinbase_offline_backtest_report.py --fixture tests/fixtures/offline_backtest/tp_hit.json --symbol ADA/USD --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Import local (no sys.path hacks in prod, but for repo layout)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import (
    BacktestResult,
    DEFAULT_ENTRY_FEE_RATE,
    DEFAULT_EXIT_FEE_RATE,
    DEFAULT_MAX_HOLD_MINUTES,
    DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE,
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
    run_backtest_from_fixture,
)

SCHEMA_VERSION = "p2-025d.coinbase_offline_backtest_report.v1"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "offline_backtest" / "tp_hit.json"


def _load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_report(
    *,
    fixture_path: Optional[Path] = None,
    symbol: str = "BTC/USD",
    strategy_name: str = "baseline_replay",
    entry_rule: str = "fixture_signal",
    take_profit_pct: float = float(DEFAULT_TAKE_PROFIT_PCT),
    stop_loss_pct: float = float(DEFAULT_STOP_LOSS_PCT),
    max_hold_minutes: int = DEFAULT_MAX_HOLD_MINUTES,
    entry_fee_rate: float = float(DEFAULT_ENTRY_FEE_RATE),
    exit_fee_rate: float = float(DEFAULT_EXIT_FEE_RATE),
    slippage_buffer_rate: float = float(DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE),
) -> Dict[str, Any]:
    fp = fixture_path or DEFAULT_FIXTURE
    result: BacktestResult = run_backtest_from_fixture(
        fp,
        symbol=symbol,
        strategy_name=strategy_name,
        entry_fee_rate=entry_fee_rate,
        exit_fee_rate=exit_fee_rate,
        slippage_buffer_rate=slippage_buffer_rate,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        max_hold_minutes=max_hold_minutes,
        entry_rule=entry_rule,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": None,  # offline, no ts needed
        "symbol": result.symbol,
        "strategy_name": result.strategy_name,
        "fixture_path": str(fp),
        "total_trades": result.total_trades,
        "wins": result.wins,
        "losses": result.losses,
        "breakeven": result.breakeven,
        "win_rate": result.win_rate,
        "gross_pnl_sum": result.gross_pnl_sum,
        "fees_sum": result.fees_sum,
        "net_pnl_sum": result.net_pnl_sum,
        "exit_reason_breakdown": result.exit_reason_breakdown,
        "closed_trades": result.closed_trades,
        "trade_permission": result.trade_permission,
        "risk_increase": result.risk_increase,
        "scaling_allowed": result.scaling_allowed,
        "notes": result.notes,
        "parameters": {
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
            "max_hold_minutes": max_hold_minutes,
            "entry_fee_rate": entry_fee_rate,
            "exit_fee_rate": exit_fee_rate,
            "slippage_buffer_rate": slippage_buffer_rate,
            "entry_rule": entry_rule,
        },
    }
    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Offline backtest report for Coinbase crypto (fixture only)")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    ap.add_argument("--fixture", type=Path, default=None, help="Path to OHLCV fixture (json/jsonl)")
    ap.add_argument("--symbol", default="BTC/USD")
    ap.add_argument("--strategy-name", default="baseline_replay")
    ap.add_argument("--entry-rule", default="fixture_signal", choices=["fixture_signal", "simple_mean_reversion"])
    ap.add_argument("--take-profit-pct", type=float, default=float(DEFAULT_TAKE_PROFIT_PCT))
    ap.add_argument("--stop-loss-pct", type=float, default=float(DEFAULT_STOP_LOSS_PCT))
    ap.add_argument("--max-hold-minutes", type=int, default=DEFAULT_MAX_HOLD_MINUTES)
    ap.add_argument("--entry-fee-rate", type=float, default=float(DEFAULT_ENTRY_FEE_RATE))
    ap.add_argument("--exit-fee-rate", type=float, default=float(DEFAULT_EXIT_FEE_RATE))
    ap.add_argument("--slippage-buffer-rate", type=float, default=float(DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE))
    args = ap.parse_args(argv)

    payload = build_report(
        fixture_path=args.fixture,
        symbol=args.symbol,
        strategy_name=args.strategy_name,
        entry_rule=args.entry_rule,
        take_profit_pct=args.take_profit_pct,
        stop_loss_pct=args.stop_loss_pct,
        max_hold_minutes=args.max_hold_minutes,
        entry_fee_rate=args.entry_fee_rate,
        exit_fee_rate=args.exit_fee_rate,
        slippage_buffer_rate=args.slippage_buffer_rate,
    )

    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
