#!/usr/bin/env python3
"""Create daily memory distillations without live broker access.

Usage
-----
  python3 scripts/daily_distill.py --date 2026-05-26
      Write markdown and full JSON summaries to memory/distillations/.

  python3 scripts/daily_distill.py --date 2026-05-26 --json
      Print compact trade-metrics JSON to stdout (for automated gating).
      Also writes the full distillation files as normal.

  python3 scripts/daily_distill.py --date 2026-05-26 --json --no-files
      Print compact JSON to stdout only; skip writing distillation files.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from memory.event_store import DEFAULT_DB_PATH, EventStore  # noqa: E402
from scripts.alpaca_no_trade_diagnose import build_diagnosis  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _query(db_path: Path, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _positions_summary() -> dict[str, Any]:
    cb_state = _load_json(ROOT / "state" / "coinbase" / "open_positions.json")
    al_state = _load_json(ROOT / "state" / "alpaca" / "open_positions.json")
    cb_positions = cb_state.get("positions", {})
    al_positions = al_state.get("positions", {})
    recovered = {
        sym: pos for sym, pos in cb_positions.items()
        if pos.get("order_status") == "broker_recovered"
    }
    external_untradeable = sum(
        float(pos.get("notional", 0.0))
        for pos in recovered.values()
        if pos.get("counts_toward_exposure", True) is not False
    )
    return {
        "coinbase_positions": cb_positions,
        "alpaca_positions": al_positions,
        "broker_recovered_positions": recovered,
        "external_untradeable_exposure": external_untradeable,
    }


def _journal_metrics(summary_date: str) -> dict[str, Any]:
    """Compute trade metrics from journal CSVs for the given date.

    Reads journal_coinbase_crypto.csv and journal_alpaca_stocks.csv.
    Only counts rows where action=EXIT or action=SELL and decision=FILLED/PLACED
    (i.e. completed exits with a recorded net P&L).
    Returns a dict suitable for capital growth plan gating.
    """
    journals = {
        "coinbase": ROOT / "journal_coinbase_crypto.csv",
        "alpaca": ROOT / "journal_alpaca_stocks.csv",
    }

    total_trades = 0
    wins = 0
    losses = 0
    breakeven = 0
    gross_pnl = 0.0
    fees_paid = 0.0
    net_pnl = 0.0
    best_trade_pnl: float | None = None
    worst_trade_pnl: float | None = None
    best_trade_sym = ""
    worst_trade_sym = ""
    entries_placed = 0

    date_prefix = summary_date[:10]  # YYYY-MM-DD

    for broker, jpath in journals.items():
        if not jpath.exists():
            continue
        try:
            with open(jpath, newline="") as f:
                for row in csv.DictReader(f):
                    ts = (row.get("timestamp") or "")[:10]
                    if ts != date_prefix:
                        continue

                    action = (row.get("action") or "").upper()
                    decision = (row.get("decision") or "").upper()

                    # Count entries placed
                    if action == "BUY" and decision in ("PLACED", "FILLED"):
                        entries_placed += 1

                    # Count completed exits
                    if action in ("EXIT", "SELL") and decision in ("FILLED", "PLACED"):
                        try:
                            pnl = float(row.get("pnl_usd") or 0.0)
                            fee = float(row.get("fees_paid") or 0.0)
                            sym = row.get("symbol") or "?"
                        except (ValueError, TypeError):
                            continue

                        total_trades += 1
                        gross_pnl += float(row.get("gross_pnl") or 0.0)
                        fees_paid += fee
                        net_pnl += pnl

                        if pnl > 0:
                            wins += 1
                        elif pnl < 0:
                            losses += 1
                        else:
                            breakeven += 1

                        if best_trade_pnl is None or pnl > best_trade_pnl:
                            best_trade_pnl = pnl
                            best_trade_sym = sym
                        if worst_trade_pnl is None or pnl < worst_trade_pnl:
                            worst_trade_pnl = pnl
                            worst_trade_sym = sym
        except Exception:
            continue

    win_rate = round(wins / total_trades, 4) if total_trades > 0 else 0.0

    return {
        "date": summary_date,
        "entries_placed": entries_placed,
        "exits_completed": total_trades,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": win_rate,
        "gross_pnl": round(gross_pnl, 6),
        "fees_paid": round(fees_paid, 6),
        "net_pnl": round(net_pnl, 6),
        "best_trade": {
            "symbol": best_trade_sym,
            "pnl": round(best_trade_pnl, 6) if best_trade_pnl is not None else None,
        },
        "worst_trade": {
            "symbol": worst_trade_sym,
            "pnl": round(worst_trade_pnl, 6) if worst_trade_pnl is not None else None,
        },
        # Capital growth plan gating fields
        "phase1_target_equity": 50.0,
        "phase1_trigger_note": (
            "When Coinbase equity >= $50 and net_pnl > 0, consider Phase 2 sizing review."
        ),
    }


def build_summary(summary_date: str, db_path: Path) -> dict[str, Any]:
    like = f"{summary_date}%"
    events = _query(
        db_path,
        "SELECT * FROM events WHERE created_at_utc LIKE ? ORDER BY created_at_utc",
        (like,),
    )
    orders = _query(
        db_path,
        """
        SELECT * FROM orders
        WHERE created_at_utc LIKE ?
          AND COALESCE(bot_name, '') != ''
        ORDER BY created_at_utc
        """,
        (like,),
    )
    risks = _query(
        db_path,
        "SELECT * FROM risk_decisions WHERE created_at_utc LIKE ? ORDER BY created_at_utc",
        (like,),
    )
    incidents = _query(
        db_path,
        "SELECT * FROM incidents WHERE created_at_utc LIKE ? ORDER BY created_at_utc",
        (like,),
    )
    runs = _query(
        db_path,
        "SELECT * FROM bot_runs WHERE created_at_utc LIKE ? ORDER BY created_at_utc",
        (like,),
    )
    positions = _positions_summary()
    heartbeats = {
        "coinbase": _load_json(ROOT / "runtime" / "coinbase_heartbeat.json"),
        "alpaca": _load_json(ROOT / "runtime" / "alpaca_heartbeat.json"),
    }
    alpaca_no_trade = build_diagnosis(root=ROOT, hours=24)
    blocked_risks = [risk for risk in risks if not bool(risk.get("allowed"))]
    placed_orders = [order for order in orders if order.get("status") not in ("preview", "blocked", "uncertain")]
    preview_orders = [order for order in orders if order.get("status") == "preview"]
    blocked_orders = [order for order in orders if order.get("status") in ("blocked", "uncertain")]

    journal_metrics = _journal_metrics(summary_date)

    return {
        "date": summary_date,
        "db_path": str(db_path),
        "journal_metrics": journal_metrics,
        "bot_runs_observed": len(runs),
        "events_count": len(events),
        "events_by_type": _count_by(events, "event_type"),
        "orders_previewed": max(len(preview_orders), len(risks)),
        "orders_placed": len(placed_orders),
        "orders_blocked": len(blocked_orders),
        "risk_decisions": len(risks),
        "risk_blocks": len(blocked_risks),
        "incidents": incidents,
        "heartbeats": heartbeats,
        "alpaca_no_trade": {
            "traded_today": alpaca_no_trade["movement"]["orders_last_24h"] > 0,
            "proposals": alpaca_no_trade["movement"]["proposals_last_24h"],
            "orders": alpaca_no_trade["movement"]["orders_last_24h"],
            "exits": alpaca_no_trade["movement"]["exits_last_24h"],
            "dominant_no_trade_reason": alpaca_no_trade["strategy"]["dominant_no_trade_reason"],
            "skip_reason_counts": alpaca_no_trade["strategy"]["skip_reasons_last_24h"],
            "risk_blocks": alpaca_no_trade["risk"]["risk_blocks_last_24h"],
            "recommended_next_action": alpaca_no_trade["conclusion"]["recommended_next_action"],
        },
        "positions": positions,
        "manual_actions_required": [
            "Transfer ETH from consumer Coinbase wallet to Advanced Trade-visible account."
        ] if positions["broker_recovered_positions"] else [],
        "recommended_next_step": (
            "Resolve Coinbase broker_recovered ETH exposure, then rerun reconciliation."
            if positions["broker_recovered_positions"]
            else "Continue paper/dry-run observation before any live-scope changes."
        ),
        "what_not_to_change_yet": [
            "Do not loosen Coinbase crypto exposure cap.",
            "Do not exclude ETH from exposure without explicit approval.",
            "Do not increase sizing, symbols, options, margin, shorts, or leverage.",
        ],
        "samples": {
            "recent_risk_blocks": blocked_risks[-5:],
            "recent_incidents": incidents[-5:],
            "recent_orders": orders[-5:],
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    hb = summary["heartbeats"]
    pos = summary["positions"]
    recovered = pos["broker_recovered_positions"]
    alpaca = summary["alpaca_no_trade"]
    lines = [
        f"# Daily Summary — {summary['date']}",
        "",
        f"1. Date: {summary['date']}",
        f"2. Bot runs observed: {summary['bot_runs_observed']}",
        f"3. Coinbase status: {hb.get('coinbase', {}).get('status', 'unknown')} "
        f"equity={hb.get('coinbase', {}).get('equity', 'unknown')}",
        f"4. Alpaca status: {hb.get('alpaca', {}).get('status', 'unknown')} "
        f"equity={hb.get('alpaca', {}).get('equity', 'unknown')}",
        f"5. Trades proposed: {summary['orders_previewed']}",
        f"6. Trades placed: {summary['orders_placed']}",
        f"7. Trades blocked: {summary['orders_blocked'] + summary['risk_blocks']}",
        f"8. P/L if available: Coinbase daily_pnl={hb.get('coinbase', {}).get('daily_pnl', 'unknown')} "
        f"Alpaca daily_pnl={hb.get('alpaca', {}).get('daily_pnl', 'unknown')}",
        f"9. Current open positions: Coinbase={len(pos['coinbase_positions'])} "
        f"Alpaca={len(pos['alpaca_positions'])}",
        f"10. Broker-recovered positions: {', '.join(recovered.keys()) if recovered else 'none'}",
        f"11. External/untradeable exposure: ${pos['external_untradeable_exposure']:.4f}",
        f"12. Risk-manager interventions: {summary['risk_blocks']}",
        f"13. Incidents/errors: {len(summary['incidents'])}",
        f"14. Alpaca traded today: {'yes' if alpaca['traded_today'] else 'no'}",
        f"15. Alpaca proposals/orders/exits: {alpaca['proposals']}/{alpaca['orders']}/{alpaca['exits']}",
        f"16. Alpaca dominant no-trade reason: {alpaca['dominant_no_trade_reason']}",
        f"17. Alpaca recommended next action: {alpaca['recommended_next_action']}",
        "18. Manual actions required:",
    ]
    actions = summary["manual_actions_required"] or ["None."]
    lines.extend([f"    - {action}" for action in actions])
    lines.extend([
        f"19. Recommended next step: {summary['recommended_next_step']}",
        "20. What not to change yet:",
    ])
    lines.extend([f"    - {item}" for item in summary["what_not_to_change_yet"]])
    lines.extend([
        "",
        "## Event Counts",
        json.dumps(summary["events_by_type"], indent=2, sort_keys=True),
        "",
        "## Alpaca No-Trade Reason Counts",
        json.dumps(alpaca["skip_reason_counts"], indent=2, sort_keys=True),
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily bot memory distillation.")
    parser.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD date to summarize.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite event store path.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "memory" / "distillations"),
        help="Directory for summary markdown/json.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Print compact trade-metrics JSON to stdout. "
            "Useful for automated capital growth plan gating. "
            "Full distillation files are still written unless --no-files is set."
        ),
    )
    parser.add_argument(
        "--no-files",
        action="store_true",
        help="Skip writing distillation files to disk (use with --json for stdout-only output).",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    # Create schema if this is the first memory command on a fresh checkout.
    EventStore(db_path)
    summary = build_summary(args.date, db_path)

    if not args.no_files:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"daily_summary_{args.date}.md"
        json_path = out_dir / f"daily_summary_{args.date}.json"
        md_path.write_text(render_markdown(summary))
        json_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")

    if args.json_output:
        # Compact metrics for programmatic use — journal metrics + key account state
        hb = summary.get("heartbeats", {})
        metrics = {
            **summary.get("journal_metrics", {}),
            "coinbase_equity": hb.get("coinbase", {}).get("equity"),
            "alpaca_equity": hb.get("alpaca", {}).get("equity"),
            "coinbase_trades_today": hb.get("coinbase", {}).get("trades_today"),
            "alpaca_trades_today": hb.get("alpaca", {}).get("trades_today"),
            "coinbase_daily_pnl": hb.get("coinbase", {}).get("daily_pnl"),
            "alpaca_daily_pnl": hb.get("alpaca", {}).get("daily_pnl"),
            "open_positions_coinbase": len(
                summary.get("positions", {}).get("coinbase_positions", {})
            ),
            "open_positions_alpaca": len(
                summary.get("positions", {}).get("alpaca_positions", {})
            ),
        }
        print(json.dumps(metrics, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
