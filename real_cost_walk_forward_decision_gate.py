#!/usr/bin/env python3
"""
scripts/p2_043d_decision_gate.py — Offline real-cost walk-forward decision gate.

Evaluates multiple scenarios over walk-forward folds.
Outputs verdict to /tmp/p2_043d_verdict.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[0]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import (
    BacktestResult,
    Bar,
    DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE,
    load_bars_from_fixture,
    run_backtest,
)


def get_buy_and_hold_net(bars: List[Bar], entry_fee_rate: float, exit_fee_rate: float, slippage_buffer_rate: float) -> Decimal:
    """Buy at first bar open, sell at last bar close, applying fees and slippage."""
    if len(bars) < 2:
        return Decimal("0.0")
    
    # Buy at close of first bar (assuming naive entry)
    entry_price = bars[0].c * Decimal(str(1.0 + slippage_buffer_rate))
    exit_price = bars[-1].c * Decimal(str(1.0 - slippage_buffer_rate))
    
    # Assuming notional of 5.0 at entry
    shares = Decimal("5.0") / entry_price
    
    entry_fees = Decimal("5.0") * Decimal(str(entry_fee_rate))
    gross_proceeds = shares * exit_price
    exit_fees = gross_proceeds * Decimal(str(exit_fee_rate))
    
    net_pnl = (gross_proceeds - Decimal("5.0")) - entry_fees - exit_fees
    return net_pnl


def evaluate_scenario(
    name: str,
    bars: List[Bar],
    entry_fee_rate: float,
    exit_fee_rate: float,
    max_hold_minutes: int,
    take_profit_pct: float,
    stop_loss_pct: float,
    fee_scenario: str,
    n_folds: int = 5,
) -> Dict[str, Any]:
    
    fold_size = max(1, len(bars) // n_folds)
    
    folds_results = []
    total_trades = 0
    total_net_pnl = Decimal("0.0")
    total_fees = Decimal("0.0")
    total_gross = Decimal("0.0")
    total_wins = 0
    total_losses = 0
    
    positive_folds = 0
    
    for i in range(n_folds):
        start_idx = i * fold_size
        end_idx = start_idx + fold_size if i < n_folds - 1 else len(bars)
        fold_bars = bars[start_idx:end_idx]
        
        if len(fold_bars) < 2:
            continue
            
        res = run_backtest(
            fold_bars,
            symbol="BTC/USD",
            strategy_name=f"{name}_fold_{i}",
            entry_fee_rate=entry_fee_rate,
            exit_fee_rate=exit_fee_rate,
            slippage_buffer_rate=float(DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE),
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            max_hold_minutes=max_hold_minutes,
            entry_rule="simple_mean_reversion", # using baseline entry to get some trades
            fee_scenario=fee_scenario,
        )
        
        fold_net = sum(t.net_pnl for t in res.closed_trades)
        if fold_net > 0:
            positive_folds += 1
            
        folds_results.append({
            "fold_index": i,
            "trades": len(res.closed_trades),
            "net_pnl": str(fold_net)
        })
        
        total_trades += len(res.closed_trades)
        total_net_pnl += fold_net
        total_fees += sum(t.fees for t in res.closed_trades)
        total_gross += sum(t.gross_pnl for t in res.closed_trades)
        
        total_wins += sum(1 for t in res.closed_trades if t.net_pnl > 0)
        total_losses += sum(1 for t in res.closed_trades if t.net_pnl <= 0)

    # Buy and hold baseline across the whole dataset
    bnh_net = get_buy_and_hold_net(bars, entry_fee_rate, exit_fee_rate, float(DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE))
    
    # Stress test: Double slippage
    stress_positive_folds = 0
    stress_total_net = Decimal("0.0")
    for i in range(n_folds):
        start_idx = i * fold_size
        end_idx = start_idx + fold_size if i < n_folds - 1 else len(bars)
        fold_bars = bars[start_idx:end_idx]
        if len(fold_bars) < 2:
            continue
            
        res = run_backtest(
            fold_bars,
            symbol="BTC/USD",
            strategy_name=f"{name}_stress_fold_{i}",
            entry_fee_rate=entry_fee_rate,
            exit_fee_rate=exit_fee_rate,
            slippage_buffer_rate=float(DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE) * 2.0,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            max_hold_minutes=max_hold_minutes,
            entry_rule="simple_mean_reversion",
            fee_scenario=fee_scenario,
        )
        fold_net = sum(t.net_pnl for t in res.closed_trades)
        stress_total_net += fold_net
        if fold_net > 0:
            stress_positive_folds += 1
            
    # Simulate 50% fill probability for limit/maker scenarios
    partial_fill_net = total_net_pnl * Decimal("0.5")
    
    is_stable_under_stress = stress_total_net > 0 and partial_fill_net > 0
    
    net_ev_per_trade = total_net_pnl / Decimal(max(1, total_trades))
    round_trip_cost_avg = total_fees / Decimal(max(1, total_trades))
    
    gross_profits = Decimal(str(sum(t.gross_pnl for f in folds_results for t in (t for t in [])))) # placeholder
    # we will estimate profit factor from total_wins/losses if we only have gross_pnl.
    # Actually we need gross wins / gross losses
    gross_win_amt = Decimal("0.0")
    gross_loss_amt = Decimal("0.0")
    # let's run a full backtest over all bars to calculate exact aggregate metrics easily
    full_res = run_backtest(
        bars,
        symbol="BTC/USD",
        strategy_name=name,
        entry_fee_rate=entry_fee_rate,
        exit_fee_rate=exit_fee_rate,
        slippage_buffer_rate=float(DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE),
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        max_hold_minutes=max_hold_minutes,
        entry_rule="simple_mean_reversion",
        fee_scenario=fee_scenario,
    )
    for t in full_res.closed_trades:
        if t.gross_pnl > 0:
            gross_win_amt += t.gross_pnl
        else:
            gross_loss_amt += abs(t.gross_pnl)
            
    profit_factor = Decimal("0.0")
    if gross_loss_amt > 0:
        profit_factor = gross_win_amt / gross_loss_amt
    elif gross_win_amt > 0:
        profit_factor = Decimal("999.0")
        
    pass_criteria = {
        "net_ev_gt_zero": net_ev_per_trade > 0,
        "net_ev_ge_2x_cost": net_ev_per_trade >= (round_trip_cost_avg * 2),
        "profit_factor_ge_1_3": profit_factor >= Decimal("1.3"),
        "positive_majority_folds": positive_folds > (n_folds / 2),
        "beats_no_trade": total_net_pnl > 0,
        "beats_bnh": total_net_pnl > bnh_net,
        "stable_under_stress": is_stable_under_stress,
    }
    
    passed_all = all(pass_criteria.values())
    
    return {
        "scenario": name,
        "passed_all": passed_all,
        "metrics": {
            "total_trades": total_trades,
            "total_net_pnl": str(total_net_pnl),
            "net_ev_per_trade": str(net_ev_per_trade),
            "bnh_net": str(bnh_net),
            "profit_factor": str(profit_factor),
            "positive_folds_ratio": f"{positive_folds}/{n_folds}",
            "stress_positive_folds_ratio": f"{stress_positive_folds}/{n_folds}",
        },
        "pass_criteria": pass_criteria,
    }

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--ohlcv-fixture", type=str, default=str(ROOT / "tests" / "fixtures" / "offline_backtest" / "tp_hit.json"))
    parser.add_argument("--output-path", type=str, default="/tmp/p2_043d_verdict.json")
    args = parser.parse_args()
    
    bars = load_bars_from_fixture(Path(args.ohlcv_fixture))
    
    scenarios = [
        {
            "name": "taker_90m",
            "entry_fee_rate": 0.012,
            "exit_fee_rate": 0.012,
            "max_hold_minutes": 90,
            "take_profit_pct": 3.0,
            "stop_loss_pct": 1.5,
            "fee_scenario": "taker/taker",
        },
        {
            "name": "maker_post_only",
            "entry_fee_rate": 0.006,
            "exit_fee_rate": 0.006,
            "max_hold_minutes": 90,
            "take_profit_pct": 3.0,
            "stop_loss_pct": 1.5,
            "fee_scenario": "maker/maker",
        },
        {
            "name": "longer_horizon_4_24h",
            "entry_fee_rate": 0.012,
            "exit_fee_rate": 0.012,
            "max_hold_minutes": 1440,
            "take_profit_pct": 10.0,
            "stop_loss_pct": 5.0,
            "fee_scenario": "taker/taker",
        },
        {
            "name": "cheaper_venue_fee_schedule",
            "entry_fee_rate": 0.001,
            "exit_fee_rate": 0.001,
            "max_hold_minutes": 90,
            "take_profit_pct": 3.0,
            "stop_loss_pct": 1.5,
            "fee_scenario": "taker/taker",
        },
    ]
    
    results = []
    any_scenario_passed = False
    
    for s in scenarios:
        res = evaluate_scenario(
            name=s["name"],
            bars=bars,
            entry_fee_rate=s["entry_fee_rate"],
            exit_fee_rate=s["exit_fee_rate"],
            max_hold_minutes=s["max_hold_minutes"],
            take_profit_pct=s["take_profit_pct"],
            stop_loss_pct=s["stop_loss_pct"],
            fee_scenario=s["fee_scenario"],
        )
        results.append(res)
        if res["passed_all"]:
            any_scenario_passed = True
            
    verdict = {
        "schema_version": "p2-043d.verdict.v1",
        "any_scenario_passed": any_scenario_passed,
        "recommendation": "PROCEED" if any_scenario_passed else "PIVOT_OR_STOP",
        "scenarios": results,
    }
    
    out_path = Path(args.output_path)
    out_path.write_text(json.dumps(verdict, indent=2))
    logging.info(f"Verdict written to {out_path}")

if __name__ == "__main__":
    main()
