#!/usr/bin/env python3
"""Read-only Coinbase position capability diagnostic.

Determines whether each open/recovered Coinbase position is:
  1. A bot-origin position with journal evidence and provable close capability.
  2. A true external consumer-wallet balance (broker_recovered, uncontrollable).
  3. An Advanced Trade-visible controllable asset.
  4. An API-visibility mismatch (visible at broker but not provably closeable).

Safety guarantees
-----------------
* This script is READ-ONLY. It never places, cancels, modifies, previews,
  or submits orders.
* It never calls close/sell/order endpoints.
* It never edits state files, .env, or any configuration.
* It never marks api_controllable=True or clears positions automatically.
* It never excludes positions from exposure.
* It does not change risk caps, notional limits, or strategy parameters.

Broker API access (optional)
-----------------------------
If LIVE_TRADING=true and valid Coinbase credentials are present, the script
calls only these read-only endpoints via BrokerCoinbase:
  - get_account()       — equity / buying power
  - get_all_positions() — all non-USD balances visible at Coinbase
  - get_order_status()  — current fill/settlement status by order_id

If broker access fails or credentials are absent, results are derived from
local state only and close capability is reported as "unknown".

Usage
-----
  python3 scripts/coinbase_position_capability_diagnose.py
  python3 scripts/coinbase_position_capability_diagnose.py --no-broker
  python3 scripts/coinbase_position_capability_diagnose.py --json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOURNAL_PATH = ROOT / "journal_coinbase_crypto.csv"
OPEN_STATE_PATH = ROOT / "state" / "coinbase" / "open_positions.json"
CLOSED_STATE_PATH = ROOT / "state" / "coinbase" / "closed_positions.json"
LOG_PATH = ROOT / "logs" / "coinbase.launchd.out.log"
HEARTBEAT_PATH = ROOT / "runtime" / "coinbase_heartbeat.json"
KILL_SWITCH_PATH = ROOT / "runtime" / "STOP_TRADING"

# These broker methods are the only ones this script will call.
# Listed here for auditability — this script calls none of the forbidden methods:
# place_limit_order, place_market_order, close_position, cancel_order,
# place_stop_order, sell, buy, submit_order.
_ALLOWED_BROKER_METHODS = frozenset({
    "get_account",
    "get_all_positions",
    "get_position",
    "get_order_status",
    "get_asset",
})


# ---------------------------------------------------------------------------
# Local file helpers (no broker access)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        return {"_load_error": str(e)}


def _safe_lines(path: Path, tail: int = 200) -> list[str]:
    try:
        with open(path) as f:
            lines = f.readlines()
        return lines[-tail:]
    except Exception:
        return []


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _heartbeat_age_seconds(hb: dict[str, Any]) -> int | str:
    raw = hb.get("last_loop_time") or hb.get("last_heartbeat_time", "")
    if not raw:
        return "unknown"
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return int((_utc_now() - ts).total_seconds())
    except Exception:
        return "unknown"


def _runtime_info() -> dict[str, Any]:
    """Collect runtime state from local files only."""
    hb = _load_json(HEARTBEAT_PATH)
    kill_switch = KILL_SWITCH_PATH.exists()
    mode = hb.get("mode", "unknown")
    live_running = (
        mode == "live"
        and not kill_switch
        and isinstance(_heartbeat_age_seconds(hb), int)
        and _heartbeat_age_seconds(hb) < 120
    )
    return {
        "mode": mode,
        "live_process_running": live_running,
        "kill_switch_active": kill_switch,
        "heartbeat_age_seconds": _heartbeat_age_seconds(hb),
        "equity": hb.get("equity", "unknown"),
    }


# ---------------------------------------------------------------------------
# Journal evidence search
# ---------------------------------------------------------------------------

def _search_journal(
    symbol: str,
    order_id: str = "",
    client_order_id: str = "",
) -> dict[str, Any]:
    """Return journal evidence for a symbol/order without loading the full file."""
    found_rows: list[dict[str, str]] = []
    matching_client_order_id = ""
    matching_order_id = ""

    sym_base = symbol.replace("/USD", "").replace("-USD", "").upper()

    try:
        with open(JOURNAL_PATH, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_sym = (row.get("symbol") or "").upper()
                row_oid = row.get("order_id") or ""
                row_coid = row.get("client_order_id") or ""

                match = False
                if order_id and row_oid == order_id:
                    match = True
                if client_order_id and row_coid == client_order_id:
                    match = True
                # Loose symbol match if no order IDs to anchor on
                if not order_id and not client_order_id:
                    if sym_base in row_sym:
                        match = True

                if match:
                    found_rows.append(dict(row))
                    if row_oid and not matching_order_id:
                        matching_order_id = row_oid
                    if row_coid and not matching_client_order_id:
                        matching_client_order_id = row_coid
    except FileNotFoundError:
        return {
            "journal_evidence_found": False,
            "journal_error": "journal file not found",
            "matching_client_order_id": "",
            "matching_order_id": "",
            "row_count": 0,
            "actions_seen": [],
        }
    except Exception as e:
        return {
            "journal_evidence_found": False,
            "journal_error": str(e),
            "matching_client_order_id": "",
            "matching_order_id": "",
            "row_count": 0,
            "actions_seen": [],
        }

    actions_seen = list(dict.fromkeys(
        r.get("action", "") for r in found_rows if r.get("action")
    ))
    return {
        "journal_evidence_found": len(found_rows) > 0,
        "journal_error": "",
        "matching_client_order_id": client_order_id or matching_client_order_id,
        "matching_order_id": order_id or matching_order_id,
        "row_count": len(found_rows),
        "actions_seen": actions_seen,
    }


# ---------------------------------------------------------------------------
# Log evidence search
# ---------------------------------------------------------------------------

def _search_log_for_order(order_id: str, client_order_id: str) -> list[str]:
    """Return log lines mentioning the order_id or client_order_id."""
    lines = _safe_lines(LOG_PATH, tail=500)
    hits = []
    for line in lines:
        if order_id and order_id in line:
            hits.append(line.rstrip())
        elif client_order_id and client_order_id in line:
            hits.append(line.rstrip())
    return hits[-5:]  # keep last 5 relevant lines


# ---------------------------------------------------------------------------
# Broker access (optional, read-only only)
# ---------------------------------------------------------------------------

def _try_broker_access(
    positions: dict[str, Any],
) -> dict[str, Any]:
    """
    Attempt read-only broker queries. Returns enriched per-symbol data.

    Only calls: get_account(), get_all_positions(), get_order_status().
    Never calls order/close/sell/cancel endpoints.
    """
    results: dict[str, Any] = {
        "broker_available": False,
        "broker_error": "",
        "account_equity": None,
        "broker_balances": {},   # symbol → market_value
        "order_status_checks": {},  # order_id → status dict
    }

    try:
        # Load .env without printing values
        env_path = ROOT / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = val

        # Import BrokerCoinbase — must succeed or we bail
        sys.path.insert(0, str(ROOT))
        from broker_coinbase import BrokerCoinbase  # type: ignore

        live_trading = os.environ.get("LIVE_TRADING", "false").lower() == "true"
        if not live_trading:
            results["broker_error"] = (
                "LIVE_TRADING is not 'true' — broker API skipped "
                "(set LIVE_TRADING=true in .env to enable live checks)"
            )
            return results

        broker = BrokerCoinbase(mode="live")

        # get_account — read-only
        account = broker.get_account()
        if account is not None:
            results["account_equity"] = getattr(account, "equity", None)

        # get_all_positions — read-only
        broker_positions = broker.get_all_positions()
        for bp in broker_positions:
            sym = getattr(bp, "symbol", "")
            mv = getattr(bp, "market_value", 0.0)
            results["broker_balances"][sym] = mv

        # get_order_status for each position that has an order_id — read-only
        for sym, pos in positions.items():
            oid = pos.get("order_id", "")
            if oid:
                status = broker.get_order_status(oid)
                if status:
                    results["order_status_checks"][oid] = status

        results["broker_available"] = True

    except ImportError as e:
        results["broker_error"] = f"BrokerCoinbase import failed: {e}"
    except Exception as e:
        results["broker_error"] = f"broker access error: {e}"

    return results


# ---------------------------------------------------------------------------
# Per-position capability analysis
# ---------------------------------------------------------------------------

def _classify_position(
    symbol: str,
    pos: dict[str, Any],
    journal: dict[str, Any],
    broker_data: dict[str, Any],
    log_hits: list[str],
) -> dict[str, Any]:
    """
    Derive capability verdict for one position.

    Does NOT mutate pos or any state. Returns a pure analysis dict.
    """
    order_id = pos.get("order_id", "")
    client_order_id = pos.get("client_order_id", "")
    order_status = pos.get("order_status", "unknown")
    api_controllable = pos.get("api_controllable", order_status != "broker_recovered")
    exit_evaluation_enabled = pos.get("exit_evaluation_enabled", order_status != "broker_recovered")
    user_action_required = pos.get("user_action_required", order_status == "broker_recovered")
    counts_toward_exposure = pos.get("counts_toward_exposure", True)
    bot_opened = pos.get("bot_opened", order_status != "broker_recovered")
    notional = float(pos.get("notional", 0.0))
    strategy = pos.get("strategy", "unknown")
    entry_price = pos.get("entry_price", 0.0)
    entry_time = pos.get("entry_time", "")
    fill_price = pos.get("fill_price", "")

    # State classification label
    if order_status == "broker_recovered":
        state_classification = "broker_recovered"
    elif order_status == "pending_new":
        state_classification = "pending_new"
    elif order_status == "filled":
        state_classification = "bot_placed_filled"
    else:
        state_classification = f"bot_placed_{order_status}"

    # Broker balance visibility
    broker_balance_visible = symbol in broker_data.get("broker_balances", {})
    broker_balance_value = broker_data.get("broker_balances", {}).get(symbol, 0.0)

    # Order status from broker (if available)
    broker_order_status = broker_data.get("order_status_checks", {}).get(order_id, {})
    broker_confirms_filled = (
        broker_order_status.get("normalized_status") == "filled"
        if broker_order_status else None
    )
    broker_settled = broker_order_status.get("settled") if broker_order_status else None

    # Determine Advanced Trade close capability
    #
    # YES:  api_controllable=True AND order_id present AND (broker confirms filled
    #       OR broker balance visible OR local state says filled)
    #
    # NO:   api_controllable=False AND user_action_required=True AND
    #       no order_id (pure consumer wallet)
    #
    # UNKNOWN: anything else — e.g. has order_id but broker unavailable,
    #          or recovered state with ambiguous origin.

    if (
        api_controllable
        and bool(order_id)
        and (
            order_status == "filled"
            or broker_confirms_filled
            or broker_balance_visible
        )
    ):
        close_capability = "yes"
    elif (
        not api_controllable
        and user_action_required
        and not bool(order_id)
    ):
        close_capability = "no"
    else:
        close_capability = "unknown"

    # Recommended action
    if close_capability == "yes" and api_controllable and exit_evaluation_enabled:
        recommended_action = (
            "normal bot-managed position; exit handled automatically by risk manager "
            "(stop-loss / take-profit / max-hold-time)"
        )
    elif close_capability == "yes" and api_controllable and not exit_evaluation_enabled:
        recommended_action = (
            "position is API-controllable but exit evaluation is disabled; "
            "verify exit_evaluation_enabled=True before relying on automated exit"
        )
    elif close_capability == "no":
        recommended_action = (
            "consumer-wallet asset — not closeable via Advanced Trade API; "
            "sell manually from coinbase.com, then clear state after confirmation"
        )
    else:
        recommended_action = (
            "keep as manual-review; do not open new entries while unresolved; "
            "verify asset location in Coinbase UI before clearing state"
        )

    return {
        "symbol": symbol,
        "state_classification": state_classification,
        "strategy": strategy,
        "notional": notional,
        "entry_price": entry_price,
        "entry_time": entry_time,
        "fill_price": fill_price,
        "bot_opened": bot_opened,
        "api_controllable": api_controllable,
        "exit_evaluation_enabled": exit_evaluation_enabled,
        "user_action_required": user_action_required,
        "counts_toward_exposure": counts_toward_exposure,
        "order_id": order_id,
        "client_order_id": client_order_id,
        "journal_evidence_found": journal["journal_evidence_found"],
        "journal_actions_seen": journal["actions_seen"],
        "journal_row_count": journal["row_count"],
        "matching_client_order_id": journal["matching_client_order_id"],
        "matching_order_id": journal["matching_order_id"],
        "broker_balance_visible": broker_balance_visible,
        "broker_balance_value": broker_balance_value,
        "broker_confirms_filled": broker_confirms_filled,
        "broker_settled": broker_settled,
        "advanced_trade_close_capability": close_capability,
        "recommended_action": recommended_action,
        "recent_log_hits": log_hits,
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_diagnostic(use_broker: bool = True) -> dict[str, Any]:
    runtime = _runtime_info()

    # Load open positions
    open_state = _load_json(OPEN_STATE_PATH)
    positions: dict[str, Any] = open_state.get("positions", {})
    load_error = open_state.get("_load_error", "")

    # Load closed positions for context
    closed_state = _load_json(CLOSED_STATE_PATH)
    closed_positions: dict[str, Any] = closed_state.get("positions", {})

    # Summarise position counts
    total = len(positions)
    broker_recovered_count = sum(
        1 for p in positions.values() if p.get("order_status") == "broker_recovered"
    )
    manual_review_count = sum(
        1 for p in positions.values()
        if p.get("user_action_required") is True
        and not (
            p.get("manual_review_entry_override_approved") is True
            and p.get("manual_review_entry_override_scope") == "allow_new_crypto_entries"
        )
    )
    non_controllable_count = sum(
        1 for p in positions.values()
        if p.get("api_controllable") is False or p.get("exit_evaluation_enabled") is False
    )
    pending_count = sum(
        1 for p in positions.values() if p.get("order_status") == "pending_new"
    )
    filled_count = sum(
        1 for p in positions.values() if p.get("order_status") == "filled"
    )

    # Broker data (optional)
    broker_data: dict[str, Any] = {
        "broker_available": False,
        "broker_error": "broker check skipped (--no-broker)",
        "account_equity": None,
        "broker_balances": {},
        "order_status_checks": {},
    }
    if use_broker:
        broker_data = _try_broker_access(positions)

    # Per-position analysis
    position_analyses: list[dict[str, Any]] = []
    for symbol, pos in positions.items():
        order_id = pos.get("order_id", "")
        client_order_id = pos.get("client_order_id", "")
        journal = _search_journal(symbol, order_id=order_id, client_order_id=client_order_id)
        log_hits = _search_log_for_order(order_id, client_order_id)
        analysis = _classify_position(symbol, pos, journal, broker_data, log_hits)
        position_analyses.append(analysis)

    # Closed-position context (last 3, for reference)
    recent_closed = list(closed_positions.items())[-3:]

    return {
        "generated_at": _utc_now().isoformat(),
        "runtime": runtime,
        "state": {
            "state_file": str(OPEN_STATE_PATH),
            "load_error": load_error,
            "open_positions_count": total,
            "broker_recovered_count": broker_recovered_count,
            "manual_review_open_count": manual_review_count,
            "non_controllable_open_count": non_controllable_count,
            "pending_count": pending_count,
            "filled_count": filled_count,
        },
        "broker": {
            "broker_available": broker_data["broker_available"],
            "broker_error": broker_data["broker_error"],
            "account_equity": broker_data["account_equity"],
        },
        "positions": position_analyses,
        "recent_closed_positions": [
            {"key": k, "order_status": v.get("order_status", "?"),
             "cleared_at": v.get("cleared_at", ""), "archived_at": v.get("archived_at", "")}
            for k, v in recent_closed
        ],
    }


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------

def _print_text(report: dict[str, Any]) -> None:
    r = report
    rt = r["runtime"]
    st = r["state"]
    br = r["broker"]

    print("=" * 60)
    print("COINBASE POSITION CAPABILITY DIAGNOSIS")
    print("=" * 60)
    print(f"Generated : {r['generated_at']}")
    print()
    print("Runtime:")
    print(f"  mode                 : {rt['mode']}")
    print(f"  live_process_running : {rt['live_process_running']}")
    print(f"  kill_switch_active   : {rt['kill_switch_active']}")
    hb_age = rt["heartbeat_age_seconds"]
    hb_str = f"{hb_age}s ago" if isinstance(hb_age, int) else hb_age
    print(f"  heartbeat_age        : {hb_str}")
    if rt.get("equity") not in (None, "unknown"):
        print(f"  last_known_equity    : ${rt['equity']}")
    print()

    print("State:")
    print(f"  open_positions_count      : {st['open_positions_count']}")
    print(f"  broker_recovered_count    : {st['broker_recovered_count']}")
    print(f"  manual_review_open_count  : {st['manual_review_open_count']}")
    print(f"  non_controllable_count    : {st['non_controllable_open_count']}")
    print(f"  pending_count             : {st['pending_count']}")
    print(f"  filled_count              : {st['filled_count']}")
    if st.get("load_error"):
        print(f"  ⚠️  state load error       : {st['load_error']}")
    print()

    print("Broker:")
    print(f"  broker_available : {br['broker_available']}")
    if br["broker_error"]:
        print(f"  broker_note      : {br['broker_error']}")
    if br["account_equity"] is not None:
        print(f"  account_equity   : ${br['account_equity']:.4f}")
    print()

    if not r["positions"]:
        print("Positions: (none)")
        print()
    else:
        for pa in r["positions"]:
            cap = pa["advanced_trade_close_capability"].upper()
            cap_icon = {"YES": "✅", "NO": "❌", "UNKNOWN": "⚠️ "}.get(cap, "?")
            print(f"Position: {pa['symbol']}")
            print(f"  state_classification       : {pa['state_classification']}")
            print(f"  strategy                   : {pa['strategy']}")
            print(f"  notional                   : ${pa['notional']:.4f}")
            print(f"  entry_price                : {pa['entry_price']}")
            if pa["fill_price"]:
                print(f"  fill_price                 : {pa['fill_price']}")
            print(f"  bot_opened                 : {pa['bot_opened']}")
            print(f"  api_controllable           : {pa['api_controllable']}")
            print(f"  exit_evaluation_enabled    : {pa['exit_evaluation_enabled']}")
            print(f"  user_action_required       : {pa['user_action_required']}")
            print(f"  counts_toward_exposure     : {pa['counts_toward_exposure']}")
            print(f"  order_id                   : {pa['order_id'] or '(none)'}")
            print(f"  client_order_id            : {pa['client_order_id'] or '(none)'}")
            print()
            print(f"  journal_evidence_found     : {pa['journal_evidence_found']}")
            if pa["journal_evidence_found"]:
                print(f"  journal_row_count          : {pa['journal_row_count']}")
                print(f"  journal_actions_seen       : {pa['journal_actions_seen']}")
                if pa["matching_client_order_id"]:
                    print(f"  matching_client_order_id   : {pa['matching_client_order_id']}")
            print()
            print(f"  broker_balance_visible     : {pa['broker_balance_visible']}")
            if pa["broker_balance_visible"]:
                print(f"  broker_balance_value       : ${pa['broker_balance_value']:.4f}")
            if pa["broker_confirms_filled"] is not None:
                print(f"  broker_confirms_filled     : {pa['broker_confirms_filled']}")
            if pa["broker_settled"] is not None:
                print(f"  broker_settled             : {pa['broker_settled']}")
            print()
            print(f"  advanced_trade_close_capability : {cap_icon} {cap}")
            print(f"  recommended_action         : {pa['recommended_action']}")
            if pa["recent_log_hits"]:
                print()
                print("  recent log evidence:")
                for line in pa["recent_log_hits"]:
                    print(f"    {line[:120]}")
            print()

    if r["recent_closed_positions"]:
        print("Recent closed/archived positions (reference):")
        for cp in r["recent_closed_positions"]:
            ts = cp.get("cleared_at") or cp.get("archived_at") or "?"
            print(f"  {cp['key']} | status={cp['order_status']} | {ts[:10]}")
        print()

    # Summary verdict
    unresolved = [
        pa for pa in r["positions"]
        if pa["advanced_trade_close_capability"] != "yes"
        or pa["user_action_required"]
    ]
    if not unresolved:
        print("✅ VERDICT: All tracked positions are bot-managed and closeable via Advanced Trade API.")
    else:
        print(f"⚠️  VERDICT: {len(unresolved)} position(s) require manual review or action:")
        for pa in unresolved:
            cap = pa["advanced_trade_close_capability"].upper()
            print(f"  {pa['symbol']}: close_capability={cap} | user_action_required={pa['user_action_required']}")
        print("  Run this diagnostic again after resolving or after broker access is confirmed.")
    print()
    print("No state was mutated. No order endpoints were called.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Coinbase position capability diagnostic."
    )
    parser.add_argument(
        "--no-broker",
        action="store_true",
        help="Skip live broker API calls; analyse local state only.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print JSON instead of human-readable text.",
    )
    args = parser.parse_args()

    use_broker = not args.no_broker
    report = run_diagnostic(use_broker=use_broker)

    if args.json_output:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_text(report)

    # Exit 1 if any position needs manual review
    needs_action = any(
        pa["user_action_required"] or pa["advanced_trade_close_capability"] != "yes"
        for pa in report["positions"]
    )
    return 1 if needs_action else 0


if __name__ == "__main__":
    sys.exit(main())
