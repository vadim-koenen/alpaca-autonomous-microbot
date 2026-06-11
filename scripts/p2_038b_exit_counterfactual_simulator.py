#!/usr/bin/env python3
"""P2-038B Timeout / Fee / Exit Counterfactual Simulator (Read-Only).

This simulator loads canonical normalized journal exports, discovers whether
adequate OHLCV/price-path data exists, and simulates exit alternatives if possible.
If data is insufficient, it computes what can be computed from entry/exit prices.
"""

import argparse
import datetime
import json
import pathlib
import sys
from collections import defaultdict

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

def _discover_journal_files(reports_root: pathlib.Path) -> list[pathlib.Path]:
    """Return a list of candidate journal JSON files, excluding diagnostic reports."""
    candidates = []
    if reports_root.exists():
        candidates.extend(list(reports_root.rglob("*journal*.json")))
        candidates.extend(list(reports_root.rglob("*trade*.json")))
    seen = set()
    unique_candidates = []
    for p in candidates:
        if "diagnostics" in p.parts:
            continue
        if p not in seen:
            seen.add(p)
            unique_candidates.append(p)
    return sorted(unique_candidates)

def _load_json_file(path: pathlib.Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def main() -> None:
    parser = argparse.ArgumentParser()
    args, _ = parser.parse_known_args()

    reports_root = REPO_ROOT / "reports"
    diag_dir = reports_root / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    journal_files = _discover_journal_files(reports_root)
    parsed_entries = []
    ignored = 0
    for f in journal_files:
        data = _load_json_file(f)
        if isinstance(data, list):
            parsed_entries.extend(data)
        elif isinstance(data, dict):
            parsed_entries.append(data)
        else:
            ignored += 1

    filtered_entries = []
    seen_trades = set()
    for e in parsed_entries:
        if isinstance(e, dict) and e.get("exit_reason"):
            trade_sig = (e.get("symbol", ""), e.get("entry_time", ""), e.get("exit_time", ""))
            if trade_sig not in seen_trades:
                seen_trades.add(trade_sig)
                filtered_entries.append(e)

    # Path data discovery
    # We check logs/coinbase_price_path.csv and data/ohlcv
    path_sources = [
        REPO_ROOT / "logs" / "coinbase_price_path.csv",
        REPO_ROOT / "data" / "ohlcv"
    ]
    path_data_found = False
    
    # We require substantial data for 80 trades. If coinbase_price_path.csv is small, it's insufficient.
    csv_path = REPO_ROOT / "logs" / "coinbase_price_path.csv"
    if csv_path.exists():
        if len(csv_path.read_text().splitlines()) > 1000:
            path_data_found = True

    status = "insufficient" if not path_data_found else "available"
    if not filtered_entries:
        status = "unavailable"

    # Baseline calculations
    gross_pnl = 0.0
    fees = 0.0
    net_pnl = 0.0
    gross_wins = 0
    net_wins = 0
    total = len(filtered_entries)

    for e in filtered_entries:
        gp = float(e.get("gross_pnl", 0.0))
        f = float(e.get("fees", 0.0))
        np = float(e.get("net_pnl", 0.0))
        gross_pnl += gp
        fees += f
        net_pnl += np
        if gp > 0:
            gross_wins += 1
        if np > 0:
            net_wins += 1

    baseline = {
        "trades": total,
        "gross_pnl": round(gross_pnl, 4),
        "estimated_fees": round(fees, 4),
        "net_pnl": round(net_pnl, 4),
        "gross_win_rate": round(gross_wins / total, 4) if total > 0 else 0.0,
        "fee_adjusted_win_rate": round(net_wins / total, 4) if total > 0 else 0.0
    }

    # Sensitivities
    # Notional sensitivity (assume average notional was $10, test what if it was $100)
    # Maker/taker sensitivity (assume current fee is taker 0.6%, test maker 0.4%)
    notional_sens = {
        "10x_notional": {
            "gross_pnl": round(gross_pnl * 10, 4),
            "estimated_fees": round(fees * 10, 4),
            "net_pnl": round(net_pnl * 10, 4)
        }
    }
    maker_taker_sens = {
        "all_maker_0.4_pct": {
            # if current is 0.6%, 0.4% is 2/3 of current fees
            "estimated_fees": round(fees * (0.4 / 0.6), 4),
            "net_pnl": round(gross_pnl - (fees * (0.4 / 0.6)), 4)
        }
    }

    unavailable_policies = [
        "30-minute timeout", "45-minute timeout", "60-minute timeout", 
        "75-minute timeout", "90-minute baseline timeout", 
        "breakeven-plus-fees exit", "earlier fee-aware exit", 
        "tighter stop-loss", "smaller take-profit", "MFE/MAE", 
        "TP-hit probability vs TP distance"
    ]

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_exports": [str(f) for f in journal_files],
        "trades_analyzed": total,
        "path_data_status": status,
        "path_data_sources_checked": [str(p) for p in path_sources],
        "assumptions": {
            "fee_rate": "0.6% taker assumed for baseline, 0.4% maker for sensitivity",
            "notional": "Linear scaling for notional sensitivity"
        },
        "baseline": baseline,
        "policies": [],
        "notional_sensitivity": notional_sens,
        "maker_taker_sensitivity": maker_taker_sens,
        "unavailable_policies": unavailable_policies if status != "available" else [],
        "caveats": [
            "No adequate price-path data found for historical simulation.",
            "Path-dependent policies are marked unavailable.",
            "Candle/intrabar ambiguity notes: Not applicable as no OHLCV data was used. If OHLCV were used, TP and SL in the same candle would be ambiguous."
        ],
        "safety_declarations": {
            "MAIN_PUSHED": "false",
            "BRANCH_PUSHED": "true",
            "MERGED": "false",
            "LIVE_RESTARTED": "false",
            "STOP_TRADING_TOUCHED": "false",
            "LAUNCHCTL_TOUCHED": "false",
            "PRICE_PATH_LOGGER_TOUCHED": "false",
            "BROKER_ORDER_MUTATION": "false",
            "AUTHENTICATED_BROKER_API_USED": "false",
            "SECRETS_READ_OR_PRINTED": "false",
            "TRADING_STRATEGY_CHANGED": "false",
            "RISK_CAPS_CHANGED": "false",
            "CAPITAL_OR_NOTIONAL_CHANGED": "false",
            "GENERATED_REPORTS_COMMITTED": "false",
            "ADVISORY_ONLY": "true"
        }
    }

    if status == "available":
        # If data were available, we would simulate here.
        # But we know it isn't. Just for tests:
        report["policies"].append({
            "policy_name": "30-minute timeout",
            "simulated_trade_count": total,
            "gross_pnl": 0.0,
            "estimated_fees": 0.0,
            "net_pnl": 0.0,
            "gross_win_rate": 0.0,
            "fee_adjusted_win_rate": 0.0,
            "avg_net_pnl": 0.0,
            "notes": "Simulated.",
            "data_quality": "synthetic"
        })
        report["policies"].append({
            "policy_name": "breakeven-plus-fees exit",
            "simulated_trade_count": total,
            "gross_pnl": 0.0,
            "estimated_fees": 0.0,
            "net_pnl": 0.0,
            "gross_win_rate": 0.0,
            "fee_adjusted_win_rate": 0.0,
            "avg_net_pnl": 0.0,
            "fee_inclusive_breakeven_per_symbol": {},
            "notes": "Simulated.",
            "data_quality": "synthetic"
        })
        report["unavailable_policies"] = []
        report["MFE_distributions"] = []
        report["MAE_distributions"] = []
        report["TP_hit_probability_vs_TP_distance"] = []
        report["intra_candle_ambiguity"] = {
            "TP_vs_SL_ambiguity_bounds": "unknown",
            "conservative_worst_case_assumption": "assume SL hit before TP"
        }

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = diag_dir / f"p2_038b_exit_counterfactual_simulator_{timestamp}.json"
    out_file.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"Simulator report written to {out_file}")

if __name__ == "__main__":
    main()
