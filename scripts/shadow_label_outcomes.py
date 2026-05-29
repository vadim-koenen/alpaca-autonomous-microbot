#!/usr/bin/env python3
"""Label shadow learner prediction outcomes from read-only local evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.outcome_labeler import (
    PriceObservation,
    classify_prediction_outcome,
    fetch_predictions_for_labeling,
    write_outcome,
)
from shadow_learner.price_history import (
    PricePoint,
    fetch_price_observations,
    read_price_file as read_price_points_file,
)
from shadow_learner.schema import connect, init_db

LOCAL_TZ = ZoneInfo("America/Chicago")
LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| "
    r"(?P<level>[A-Z]+)\s+\| (?P<component>[^|]+) \| (?P<message>.*)$"
)
SYMBOL_RE = re.compile(r"\b(?P<symbol>[A-Z0-9]+/[A-Z0-9]+|[A-Z.]{1,6})\b")
PRICE_FIELDS = (
    re.compile(r"\bexit=(?P<price>-?\d+(?:\.\d+)?)"),
    re.compile(r"\bclose=(?P<price>-?\d+(?:\.\d+)?)"),
    re.compile(r"\blimit=(?P<price>-?\d+(?:\.\d+)?)"),
    re.compile(r"\bprice=(?P<price>-?\d+(?:\.\d+)?)"),
    re.compile(r"\blast=(?P<price>-?\d+(?:\.\d+)?)"),
)


def redact_for_output(text: str) -> str:
    return redact_text(text)


def _parse_since(value: str | None) -> str | None:
    if not value:
        return None
    if "T" in value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_log_time(value: str) -> str:
    local = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
    return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_price(message: str) -> float | None:
    for pattern in PRICE_FIELDS:
        match = pattern.search(message)
        if match:
            price = _safe_float(match.group("price"))
            if price and price > 0:
                return price
    return None


def _extract_symbol(message: str) -> str:
    match = SYMBOL_RE.search(message)
    return match.group("symbol") if match else ""


def parse_price_observation_line(
    raw_line: str,
    *,
    source: str,
    since_utc: str | None = None,
) -> PriceObservation | None:
    match = LOG_RE.match(raw_line.rstrip("\n"))
    if not match:
        return None
    timestamp_utc = _parse_log_time(match.group("ts"))
    if since_utc and timestamp_utc < since_utc:
        return None
    message = match.group("message")
    symbol = _extract_symbol(message)
    price = _extract_price(message)
    if not symbol or not price:
        return None
    terminal = "EXIT triggered" in message or "| EXIT |" in message
    return PriceObservation(
        symbol=symbol,
        timestamp_utc=timestamp_utc,
        price=price,
        source=source,
        terminal=terminal,
    )


def collect_log_price_observations(
    *,
    logs_root: Path,
    broker: str,
    since_utc: str | None,
) -> list[PriceObservation]:
    sources = []
    if broker in {"all", "coinbase"}:
        sources.append(("coinbase", logs_root / "coinbase.launchd.out.log"))
    if broker in {"all", "alpaca"}:
        sources.append(("alpaca", logs_root / "alpaca.launchd.out.log"))
    observations: list[PriceObservation] = []
    for source_broker, path in sources:
        if not path.exists():
            continue
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    obs = parse_price_observation_line(
                        raw_line,
                        source=f"log:{rel.as_posix()}",
                        since_utc=since_utc,
                    )
                    if obs is not None:
                        observations.append(obs)
        except OSError:
            continue
    return observations


def read_price_file(path: str | Path) -> list[PriceObservation]:
    points, _errors = read_price_points_file(path)
    return [_point_to_observation(point, source=f"price_file:{Path(path).name}") for point in points]


def _point_to_observation(point: PricePoint, *, source: str | None = None) -> PriceObservation:
    return PriceObservation(
        symbol=point.symbol,
        timestamp_utc=point.timestamp_utc,
        price=point.close,
        source=source or f"price_history:{point.source}",
        open=point.open,
        high=point.high,
        low=point.low,
        close=point.close,
        volume=point.volume,
        timeframe=point.timeframe,
    )


def _existing_outcome_count(db_path: str | Path | None) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM shadow_outcomes").fetchone()[0])


def label_outcomes(
    *,
    db_path: str | Path | None,
    since_utc: str | None,
    broker: str,
    observations: list[PriceObservation],
    dry_run: bool,
) -> dict[str, Any]:
    target_broker = None if broker == "all" else broker
    predictions = fetch_predictions_for_labeling(
        db_path=db_path,
        since_utc=since_utc,
        broker=target_broker,
    )
    summary: dict[str, Any] = {
        "predictions_considered": len(predictions),
        "price_observations": len(observations),
        "written": 0,
        "dry_run": dry_run,
        "status_counts": Counter(),
        "by_broker": Counter(),
        "by_symbol": Counter(),
        "before_rows": 0 if dry_run else _existing_outcome_count(db_path),
        "after_rows": 0,
    }
    for prediction in predictions:
        try:
            result = classify_prediction_outcome(prediction, observations)
        except Exception as exc:  # defensive: outcome labeling must fail closed
            result = {
                "outcome_status": "error",
                "horizon_minutes": int(prediction.get("horizon_minutes", 0) or 0),
                "market_data_available": False,
                "outcome_json": {"error": type(exc).__name__},
            }
        status = result["outcome_status"]
        summary["status_counts"][status] += 1
        summary["by_broker"][prediction["broker"]] += 1
        summary["by_symbol"][prediction["symbol"]] += 1
        if dry_run:
            continue
        outcome_json = dict(result.get("outcome_json", {}) or {})
        previous_status = prediction.get("existing_outcome_status")
        if previous_status:
            outcome_json["previous_status"] = previous_status
            outcome_json["relabeled_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if outcome_json.get("sources"):
                outcome_json["price_source_used"] = outcome_json["sources"]
        write_outcome(
            prediction_id=prediction["prediction_id"],
            horizon_minutes=int(result["horizon_minutes"]),
            outcome_status=status,
            db_path=db_path,
            future_return_pct=result.get("future_return_pct"),
            max_favorable_excursion_pct=result.get("max_favorable_excursion_pct"),
            max_adverse_excursion_pct=result.get("max_adverse_excursion_pct"),
            hit_take_profit=result.get("hit_take_profit"),
            hit_stop_loss=result.get("hit_stop_loss"),
            market_data_available=bool(result.get("market_data_available")),
            outcome_json=outcome_json,
        )
        summary["written"] += 1
    summary["after_rows"] = summary["before_rows"] if dry_run else _existing_outcome_count(db_path)
    return summary


def _format_counter(counter: Counter[str]) -> list[str]:
    if not counter:
        return ["  none"]
    return [f"  {key}: {value}" for key, value in counter.most_common()]


def build_output(summary: dict[str, Any]) -> str:
    lines = [
        "Shadow Outcome Labeler",
        f"Mode: {'dry-run' if summary['dry_run'] else 'write'}",
        f"Predictions considered: {summary['predictions_considered']}",
        f"Price observations: {summary['price_observations']}",
        f"Outcomes written: {summary['written']}",
        f"Outcome rows before: {summary['before_rows']}",
        f"Outcome rows after: {summary['after_rows']}",
        "",
        "Status counts:",
        *_format_counter(summary["status_counts"]),
        "",
        "Count by broker:",
        *_format_counter(summary["by_broker"]),
        "",
        "Count by symbol:",
        *_format_counter(summary["by_symbol"]),
        "",
        "Recommendation: advisory only; not used for live trading",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="UTC date or timestamp lower bound")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing outcomes")
    parser.add_argument("--broker", default="all", choices=["all", "alpaca", "coinbase"])
    parser.add_argument("--price-file", default=None, help="Optional JSON/JSONL manual price file")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    parser.add_argument("--logs-root", default=str(ROOT / "logs"))
    args = parser.parse_args()

    since_utc = _parse_since(args.since)
    observations = collect_log_price_observations(
        logs_root=Path(args.logs_root),
        broker=args.broker,
        since_utc=since_utc,
    )
    observations.extend(fetch_price_observations(db_path=args.db, since_utc=since_utc))
    if args.price_file:
        observations.extend(read_price_file(args.price_file))
    summary = label_outcomes(
        db_path=args.db,
        since_utc=since_utc,
        broker=args.broker,
        observations=observations,
        dry_run=args.dry_run,
    )
    print(redact_for_output(build_output(summary)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
