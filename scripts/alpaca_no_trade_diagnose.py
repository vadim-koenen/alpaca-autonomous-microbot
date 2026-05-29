#!/usr/bin/env python3
"""Explain recent Alpaca no-trade behavior from local files only.

This script is read-only. It does not import broker adapters, place orders,
cancel orders, restart bots, or call main.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

SKIP_REASON_PATTERNS = (
    ("invalid_quote", re.compile(r"invalid quote", re.I)),
    ("stale_quote", re.compile(r"stale quote", re.I)),
    ("no_bars", re.compile(r"no bars", re.I)),
    ("insufficient_bars", re.compile(r"insufficient bars|only \d+ bars", re.I)),
    ("spread_too_wide", re.compile(r"spread too wide|spread=.*> max", re.I)),
    ("conditions_failed", re.compile(r"conditions failed", re.I)),
    ("confidence_below_threshold", re.compile(r"confidence below threshold|conf=.*< min", re.I)),
)

SYMBOL_RE = re.compile(r"SCAN\s+(?P<symbol>[A-Z][A-Z0-9.\-]*)\s+(?P<context>equity|starter|momentum_breakout|vwap_reversion)")
RISK_BLOCK_RE = re.compile(r"(ENTRY_BLOCKED reason=[^\s|]+|RISK BLOCK \[[^\]]+\]: [^—]+— .*)")


def build_diagnosis(
    *,
    root: Path = ROOT,
    hours: int = 24,
    since: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if since:
        cutoff = _parse_since_date(since)
        window = {
            "mode": "since",
            "since": since,
            "cutoff_utc": cutoff.isoformat(),
            "hours": None,
        }
        log_cutoff = cutoff
    else:
        cutoff = now - timedelta(hours=hours)
        window = {
            "mode": "hours",
            "since": "",
            "cutoff_utc": cutoff.isoformat(),
            "hours": hours,
        }
        # Preserve historical --hours behavior: journal counts use the cutoff,
        # while log-derived skip counts summarize the available local log file.
        log_cutoff = None
    config = _load_config(root / "config_alpaca_stocks.yaml")
    symbols = list((config.get("equities") or {}).get("symbols") or [])
    heartbeat = _load_json(root / "runtime" / "alpaca_heartbeat.json")
    log_path = root / "logs" / "alpaca.launchd.out.log"
    journal_path = root / "journal_alpaca_stocks.csv"

    log_summary = parse_alpaca_log(log_path, symbols=symbols, cutoff=log_cutoff)
    journal_summary = parse_alpaca_journal(journal_path, cutoff=cutoff)
    market_hint = market_session_hint(now)
    risk_cap = ((config.get("global_risk") or {}).get("max_total_live_exposure_usd", "unknown"))

    dominant_reason = _dominant_reason(log_summary["skip_reason_counts"])
    primary_reason = dominant_reason or "unknown"
    if market_hint["likely_open"] is False and dominant_reason in {"no_bars", "insufficient_bars", "stale_quote", "invalid_quote", None}:
        primary_reason = market_hint["reason"]
    elif journal_summary["proposals_last_24h"] == 0 and dominant_reason:
        primary_reason = dominant_reason
    elif journal_summary["proposals_last_24h"] > 0 and journal_summary["orders_last_24h"] == 0:
        primary_reason = "proposal_blocked_or_not_filled"

    return {
        "analysis_window": window,
        "runtime": {
            "heartbeat_age_seconds": _heartbeat_age_seconds(heartbeat, now),
            "heartbeat_status": heartbeat.get("status", "unknown"),
            "config_file": "config_alpaca_stocks.yaml",
            "mode": heartbeat.get("mode", config.get("mode", "unknown")),
            "launchd_label": "com.vadim.alpaca-stocks-bot",
            "latest_code_loaded": "unknown",
        },
        "account_permission": {
            "last_account_health": _last_matching_line(log_path, "PERMISSIONS:"),
            "last_auth_error": _last_matching_line(log_path, "auth"),
            "alpaca_crypto_allowed": False,
            "margin_allowed": bool((config.get("live_trading") or {}).get("allow_margin", False)),
            "shorting_allowed": bool((config.get("live_trading") or {}).get("allow_short_selling", False)),
        },
        "market_session": market_hint,
        "symbols": _symbol_details(symbols, log_summary),
        "strategy": {
            "proposals_last_24h": journal_summary["proposals_last_24h"],
            "skip_reasons_last_24h": log_summary["skip_reason_counts"],
            "dominant_no_trade_reason": dominant_reason or "unknown",
        },
        "movement": journal_summary,
        "risk": {
            "aggregate_exposure": _alpaca_state_exposure(root),
            "global_exposure_cap": risk_cap,
            "max_open_positions": (config.get("global_risk") or {}).get("max_open_positions", "unknown"),
            "duplicate_order_guard_status": "enabled",
            "last_entry_block_reason": log_summary["last_risk_block"] or "none",
            "risk_blocks_last_24h": log_summary["risk_blocks"],
        },
        "conclusion": {
            "primary_no_trade_reason": primary_reason,
            "recommended_next_action": _recommended_action(primary_reason),
        },
    }


def parse_alpaca_log(
    log_path: Path,
    *,
    symbols: list[str],
    cutoff: datetime | None = None,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    symbol_details: dict[str, dict[str, Any]] = {
        sym: {
            "last_quote_status": "unknown",
            "last_bars_status": "unknown",
            "last_skip_reason": "unknown",
            "last_strategy_result": "unknown",
            "last_risk_result": "unknown",
        }
        for sym in symbols
    }
    risk_blocks: list[str] = []

    for line in _safe_lines(log_path):
        if cutoff is not None:
            ts = _parse_log_line_ts(line)
            if ts is None or ts < cutoff:
                continue
        risk_match = RISK_BLOCK_RE.search(line)
        if risk_match:
            risk_blocks.append(risk_match.group(1).strip())

        symbol_match = SYMBOL_RE.search(line)
        symbol = symbol_match.group("symbol") if symbol_match else ""
        reason = categorize_skip_reason(line)
        if reason:
            counts[reason] += 1
            if symbol:
                detail = symbol_details.setdefault(symbol, {})
                detail["last_skip_reason"] = reason
                detail["last_strategy_result"] = "skipped"
                if reason in {"invalid_quote", "stale_quote"}:
                    detail["last_quote_status"] = reason
                if reason in {"no_bars", "insufficient_bars"}:
                    detail["last_bars_status"] = reason

        if symbol and "SIGNAL" in line:
            symbol_details.setdefault(symbol, {})["last_strategy_result"] = "proposal_generated"

    return {
        "skip_reason_counts": dict(counts),
        "symbols": symbol_details,
        "risk_blocks": risk_blocks[-10:],
        "last_risk_block": risk_blocks[-1] if risk_blocks else "",
    }


def parse_alpaca_journal(journal_path: Path, *, cutoff: datetime) -> dict[str, Any]:
    proposals = orders = exits = 0
    last_trade_at = ""
    last_exit_at = ""

    if not journal_path.exists():
        return {
            "proposals_last_24h": 0,
            "orders_last_24h": 0,
            "exits_last_24h": 0,
            "last_trade_at": "",
            "last_exit_at": "",
        }

    with journal_path.open(newline="") as f:
        for row in csv.DictReader(f):
            ts = _parse_ts(row.get("timestamp", ""))
            if ts is None or ts < cutoff:
                continue
            decision = (row.get("decision") or "").upper()
            action = (row.get("action") or "").upper()
            if decision == "PREVIEW":
                proposals += 1
            if decision == "PLACED":
                orders += 1
                last_trade_at = row.get("timestamp", "") or last_trade_at
            if action == "EXIT":
                exits += 1
                last_exit_at = row.get("timestamp", "") or last_exit_at

    return {
        "proposals_last_24h": proposals,
        "orders_last_24h": orders,
        "exits_last_24h": exits,
        "last_trade_at": last_trade_at,
        "last_exit_at": last_exit_at,
    }


def categorize_skip_reason(line: str) -> str:
    for reason, pattern in SKIP_REASON_PATTERNS:
        if pattern.search(line):
            return reason
    return ""


def market_session_hint(now: datetime) -> dict[str, Any]:
    try:
        from zoneinfo import ZoneInfo

        local = now.astimezone(ZoneInfo("America/Chicago"))
    except Exception:
        local = now
    weekday = local.weekday()
    if weekday >= 5:
        return {"market_likely_open": False, "likely_open": False, "reason": "weekend"}
    if local.month == 5 and weekday == 0 and local.day >= 25:
        return {"market_likely_open": False, "likely_open": False, "reason": "possible_memorial_day"}
    open_time = local.replace(hour=8, minute=30, second=0, microsecond=0)
    close_time = local.replace(hour=15, minute=0, second=0, microsecond=0)
    likely_open = open_time <= local <= close_time
    return {
        "market_likely_open": likely_open,
        "likely_open": likely_open,
        "reason": "regular_session" if likely_open else "outside_regular_session",
    }


def render_text(diagnosis: dict[str, Any], *, brief: bool = False) -> str:
    movement = diagnosis["movement"]
    strategy = diagnosis["strategy"]
    risk = diagnosis["risk"]
    conclusion = diagnosis["conclusion"]
    counts = strategy["skip_reasons_last_24h"]
    most_common = _dominant_reason(counts) or "unknown"
    last_skip = _last_symbol_skip(diagnosis["symbols"]) or "unknown"

    if brief:
        return "\n".join([
            "--- Alpaca movement ---",
            f"  proposals_last_24h      : {movement['proposals_last_24h']}",
            f"  orders_last_24h         : {movement['orders_last_24h']}",
            f"  exits_last_24h          : {movement['exits_last_24h']}",
            f"  most_common_skip_reason : {most_common}",
            f"  last_skip_reason        : {last_skip}",
            f"  last_risk_block         : {risk['last_entry_block_reason']}",
            f"  primary_no_trade_reason : {conclusion['primary_no_trade_reason']}",
            "  diagnose                : python3 scripts/alpaca_no_trade_diagnose.py",
        ]) + "\n"

    lines = [
        "ALPACA NO-TRADE DIAGNOSIS",
        "",
        "Window:",
        f"  mode: {diagnosis.get('analysis_window', {}).get('mode', 'hours')}",
        f"  cutoff_utc: {diagnosis.get('analysis_window', {}).get('cutoff_utc', 'unknown')}",
        "",
        "Runtime:",
        f"  heartbeat_age: {diagnosis['runtime']['heartbeat_age_seconds']}",
        f"  launchd_label: {diagnosis['runtime']['launchd_label']}",
        f"  config_file: {diagnosis['runtime']['config_file']}",
        f"  mode: {diagnosis['runtime']['mode']}",
        f"  latest_code_loaded: {diagnosis['runtime']['latest_code_loaded']}",
        "",
        "Account / permission:",
        f"  last_account_health: {diagnosis['account_permission']['last_account_health'] or 'unknown'}",
        f"  last_auth_error: {diagnosis['account_permission']['last_auth_error'] or 'none'}",
        f"  alpaca_crypto_allowed: {diagnosis['account_permission']['alpaca_crypto_allowed']}",
        f"  margin_allowed: {diagnosis['account_permission']['margin_allowed']}",
        f"  shorting_allowed: {diagnosis['account_permission']['shorting_allowed']}",
        "",
        "Market/session:",
        f"  market_likely_open: {diagnosis['market_session']['market_likely_open']}",
        f"  holiday_or_weekend_hint: {diagnosis['market_session']['reason']}",
        f"  recent_market_data_available: {most_common not in {'no_bars', 'insufficient_bars', 'stale_quote', 'invalid_quote'}}",
        "",
        "Symbols:",
    ]
    for symbol, detail in diagnosis["symbols"].items():
        lines.extend([
            f"  {symbol}:",
            f"    last_quote_status: {detail.get('last_quote_status', 'unknown')}",
            f"    last_bars_status: {detail.get('last_bars_status', 'unknown')}",
            f"    last_skip_reason: {detail.get('last_skip_reason', 'unknown')}",
            f"    last_strategy_result: {detail.get('last_strategy_result', 'unknown')}",
            f"    last_risk_result: {detail.get('last_risk_result', 'unknown')}",
        ])
    lines.extend([
        "",
        "Strategy:",
        f"  proposals_last_24h: {movement['proposals_last_24h']}",
        "  skip_reasons_last_24h:",
    ])
    for reason, count in sorted(counts.items()):
        lines.append(f"    {reason}: {count}")
    lines.extend([
        "",
        "Risk:",
        f"  aggregate_exposure: {risk['aggregate_exposure']}",
        f"  global_exposure_cap: {risk['global_exposure_cap']}",
        f"  max_open_positions: {risk['max_open_positions']}",
        f"  duplicate_order_guard_status: {risk['duplicate_order_guard_status']}",
        f"  last_entry_block_reason: {risk['last_entry_block_reason']}",
        "",
        "Conclusion:",
        f"  primary_no_trade_reason: {conclusion['primary_no_trade_reason']}",
        f"  recommended_next_action: {conclusion['recommended_next_action']}",
    ])
    return "\n".join(lines) + "\n"


def _safe_lines(path: Path) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()
    except Exception:
        return []


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _load_config(path: Path) -> dict[str, Any]:
    try:
        import yaml

        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_log_line_ts(line: str) -> datetime | None:
    match = re.match(r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", line)
    if not match:
        return None
    return _parse_ts(match.group("ts"))


def _parse_since_date(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--since must use YYYY-MM-DD format"
        ) from exc
    return parsed.replace(tzinfo=timezone.utc)


def _heartbeat_age_seconds(heartbeat: dict[str, Any], now: datetime) -> int | str:
    ts = _parse_ts(str(heartbeat.get("last_loop_time", "")))
    if ts is None:
        return "unknown"
    return max(0, int((now.astimezone(timezone.utc) - ts).total_seconds()))


def _last_matching_line(log_path: Path, needle: str) -> str:
    needle = needle.lower()
    for line in reversed(_safe_lines(log_path)):
        if needle in line.lower():
            return line.strip()
    return ""


def _alpaca_state_exposure(root: Path) -> float:
    data = _load_json(root / "state" / "alpaca" / "open_positions.json")
    exposure = 0.0
    for pos in (data.get("positions") or {}).values():
        try:
            exposure += float(pos.get("notional", 0.0))
        except Exception:
            pass
    return round(exposure, 4)


def _symbol_details(symbols: list[str], log_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    details = dict(log_summary["symbols"])
    for symbol in symbols:
        details.setdefault(symbol, {
            "last_quote_status": "unknown",
            "last_bars_status": "unknown",
            "last_skip_reason": "unknown",
            "last_strategy_result": "unknown",
            "last_risk_result": "unknown",
        })
    return details


def _dominant_reason(counts: dict[str, int] | Counter[str]) -> str:
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _last_symbol_skip(symbols: dict[str, dict[str, Any]]) -> str:
    for detail in reversed(list(symbols.values())):
        reason = detail.get("last_skip_reason")
        if reason and reason != "unknown":
            return reason
    return ""


def _recommended_action(primary_reason: str) -> str:
    if primary_reason in {"no_bars", "insufficient_bars", "stale_quote", "invalid_quote", "outside_regular_session", "weekend", "possible_memorial_day"}:
        return "Wait for regular market data, then rerun scripts/status.sh and this diagnosis."
    if primary_reason == "global_exposure_cap_exceeded":
        return "Review exposure in scripts/reconcile.sh before considering any new entries."
    if primary_reason == "proposal_blocked_or_not_filled":
        return "Inspect recent risk/order blocks; do not loosen strategy gates automatically."
    return "Keep observing; no strategy weakening is recommended from this diagnosis alone."


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain recent Alpaca no-trade behavior from local files.")
    parser.add_argument("--root", default=str(ROOT), help="Project root to inspect.")
    window_group = parser.add_mutually_exclusive_group()
    window_group.add_argument("--hours", type=int, default=24, help="Recent window for journal counts.")
    window_group.add_argument(
        "--since",
        type=str,
        help="Analyze from 00:00 UTC at the start of YYYY-MM-DD. Mutually exclusive with --hours.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument("--brief", action="store_true", help="Print concise status-oriented summary.")
    args = parser.parse_args()

    if args.since:
        try:
            _parse_since_date(args.since)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))

    diagnosis = build_diagnosis(root=Path(args.root), hours=args.hours, since=args.since)
    if args.json:
        print(json.dumps(diagnosis, indent=2, sort_keys=True, default=str))
    else:
        print(render_text(diagnosis, brief=args.brief), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
