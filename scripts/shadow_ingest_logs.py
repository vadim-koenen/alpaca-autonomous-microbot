#!/usr/bin/env python3
"""Read-only offline ingestion from bot logs/state into shadow learner tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.prediction_journal import (
    generate_baseline_predictions,
    record_prediction,
)
from shadow_learner.prospective_predictions import (
    generate_prospective_predictions_for_snapshot,
    prediction_rows_for_snapshot,
    prediction_rows_for_snapshot_with_db_context,
    snapshot_row_from_feature_snapshot,
)
from shadow_learner.schema import connect, init_db, resolve_db_path

LOCAL_TZ = ZoneInfo("America/Chicago")
DEFAULT_LOGS = {
    "alpaca": ("alpaca.launchd.out.log",),
    "coinbase": ("coinbase.launchd.out.log",),
}
DEFAULT_RUNTIME = {
    "alpaca": ("alpaca_heartbeat.json",),
    "coinbase": ("coinbase_heartbeat.json",),
}
DEFAULT_STATE = {
    "alpaca": ("open_positions.json",),
    "coinbase": ("open_positions.json",),
}

LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| "
    r"(?P<level>[A-Z]+)\s+\| (?P<component>[^|]+) \| (?P<message>.*)$"
)
ALPACA_SCAN_RE = re.compile(r"\bSCAN (?P<symbol>[A-Z.]+) equity \| (?P<body>.*)$")
CRYPTO_SCAN_RE = re.compile(r"\bSCAN (?P<symbol>[A-Z0-9]+/[A-Z0-9]+)(?::|\s+)(?P<body>.*)$")
SIGNAL_RE = re.compile(
    r"\bSIGNAL (?P<strategy>[A-Za-z0-9_]+) (?P<symbol>[A-Z0-9]+/[A-Z0-9]+) \| (?P<body>.*)$"
)
JOURNAL_RE = re.compile(
    r"\b(?P<event>SKIP|EXIT|BUY|SELL|FILL|ENTRY) \| (?P<symbol>[A-Z0-9]+/[A-Z0-9]+|[A-Z.]+) "
    r"\| (?P<rest>.*)$"
)
ORDER_PLACED_RE = re.compile(
    r"\b(?:MARKET|LIMIT) ORDER PLACED: .*?\| (?P<side>BUY|SELL) (?P<symbol>[A-Z0-9]+/[A-Z0-9]+)\b"
)
EXIT_TRIGGER_RE = re.compile(r"\bEXIT triggered: (?P<symbol>[A-Z0-9]+/[A-Z0-9]+) \| (?P<body>.*)$")
COMPLETE_RE = re.compile(r"\bStrategy scan complete: (?P<count>\d+) proposal")
SYMBOL_RE = re.compile(r"\b[A-Z]{1,6}(?:/[A-Z]{2,6})?\b")
NUMBER_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=\$?(?P<value>-?\d+(?:\.\d+)?)%?")
SPREAD_TOO_WIDE_RE = re.compile(
    r"spread too wide (?P<spread>-?\d+(?:\.\d+)?)% > max=(?P<max>-?\d+(?:\.\d+)?)%"
)
INVALID_QUOTE_RE = re.compile(
    r"invalid quote.*?bid=(?P<bid>-?\d+(?:\.\d+)?).*?ask=(?P<ask>-?\d+(?:\.\d+)?)"
)
AGE_RE = re.compile(r"\bage=(?P<age>\d+(?:\.\d+)?)s\b")


@dataclass(frozen=True)
class ParsedSnapshot:
    snapshot: FeatureSnapshot
    source_kind: str
    should_predict: bool
    would_trade: bool = False
    live_trade_taken: bool = False


def redact_for_output(text: str) -> str:
    """Redact secrets/account ids before displaying or storing raw source text."""
    return redact_text(text)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_log_timestamp(value: str) -> datetime:
    local = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
    return local.astimezone(timezone.utc)


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    if "T" in value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TZ)
        return parsed.astimezone(timezone.utc)
    local = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
    return local.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, *parts: Any) -> str:
    joined = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_key_values(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for match in NUMBER_RE.finditer(text):
        key = match.group("key")
        value = _safe_float(match.group("value"))
        if value is not None:
            parsed[key] = value
    return parsed


def _extract_price(fields: dict[str, Any]) -> float | None:
    for key in ("price", "close", "limit", "entry", "exit", "last"):
        value = _safe_float(fields.get(key))
        if value and value > 0:
            return value
    return None


def _spread_from_bid_ask(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return ((ask - bid) / mid) * 100.0


def _market_status_from_body(body: str) -> tuple[str, str, int | None]:
    lower = body.lower()
    if "invalid quote" in lower:
        return "invalid_quote", "invalid_quote", 0
    if "stale quote" in lower or "stale=true" in lower:
        return "stale_quote", "stale_quote", 0
    if "no bars returned" in lower or "no_bars" in lower:
        return "no_bars", "no_bars", 0
    if "spread too wide" in lower:
        return "spread_too_wide", "spread_too_wide", 1
    if "blocked:" in lower:
        return "valid", body.split("BLOCKED:", 1)[1].strip(), 1
    if "skipped" in lower:
        return "unknown", body, None
    return "valid", "", None


def _source_features(
    *,
    source_file: Path,
    source_line: int,
    source_kind: str,
    raw_line: str,
    log_level: str = "",
    component: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "ingestion_source": f"log:{source_file.as_posix()}",
        "source_file": source_file.as_posix(),
        "source_line": source_line,
        "source_kind": source_kind,
        "raw_line_redacted": redact_for_output(raw_line),
        "log_level": log_level,
        "component": component.strip(),
        "parsed_at_utc": _utc_now(),
    }
    if extra:
        payload.update(extra)
    return payload


def _snapshot_from_log(
    *,
    broker: str,
    asset_class: str,
    symbol: str,
    strategy: str,
    source_file: Path,
    source_line: int,
    raw_line: str,
    created_at_utc: str,
    source_kind: str,
    market_data_status: str,
    skip_reason: str,
    price: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
    spread_pct: float | None = None,
    quote_age_seconds: float | None = None,
    bars_available: int | None = None,
    risk_block_reason: str = "",
    extra_features: dict[str, Any] | None = None,
    level: str = "",
    component: str = "",
) -> FeatureSnapshot:
    snapshot_id = _stable_id("snap", broker, source_file.as_posix(), source_line, raw_line)
    features = _source_features(
        source_file=source_file,
        source_line=source_line,
        source_kind=source_kind,
        raw_line=raw_line,
        log_level=level,
        component=component,
        extra=extra_features,
    )
    return FeatureSnapshot(
        snapshot_id=snapshot_id,
        created_at_utc=created_at_utc,
        broker=broker,
        asset_class=asset_class,
        symbol=symbol,
        strategy=strategy,
        scan_id=_stable_id("scan", broker, source_file.as_posix(), source_line),
        price=price,
        bid=bid,
        ask=ask,
        spread_pct=spread_pct,
        quote_age_seconds=quote_age_seconds,
        bars_available=bars_available,
        market_session="continuous" if asset_class == "crypto" else "",
        market_data_status=market_data_status,
        skip_reason=skip_reason,
        risk_block_reason=risk_block_reason,
        features=features,
    )


def _parse_alpaca_message(
    *,
    source_file: Path,
    source_line: int,
    raw_line: str,
    created_at_utc: str,
    level: str,
    component: str,
    message: str,
) -> ParsedSnapshot | None:
    match = ALPACA_SCAN_RE.search(message)
    if not match:
        return None
    symbol = match.group("symbol")
    body = match.group("body")
    if body.startswith("strategies="):
        return None

    fields = _parse_key_values(body)
    invalid = INVALID_QUOTE_RE.search(body)
    bid = _safe_float(fields.get("bid"))
    ask = _safe_float(fields.get("ask"))
    if invalid:
        bid = _safe_float(invalid.group("bid"))
        ask = _safe_float(invalid.group("ask"))
    age = AGE_RE.search(body)
    quote_age = _safe_float(age.group("age")) if age else _safe_float(fields.get("quote_age_seconds"))
    market_status, skip_reason, bars_available = _market_status_from_body(body)
    spread_match = SPREAD_TOO_WIDE_RE.search(body)
    spread_pct = _safe_float(spread_match.group("spread")) if spread_match else _spread_from_bid_ask(bid, ask)
    price = _extract_price(fields)
    extra = {
        "parsed_fields": fields,
        "max_spread_pct": _safe_float(spread_match.group("max")) if spread_match else None,
    }
    snapshot = _snapshot_from_log(
        broker="alpaca",
        asset_class="equity",
        symbol=symbol,
        strategy="scan_all",
        source_file=source_file,
        source_line=source_line,
        raw_line=raw_line,
        created_at_utc=created_at_utc,
        source_kind="alpaca_equity_scan",
        market_data_status=market_status,
        skip_reason=skip_reason,
        price=price,
        bid=bid,
        ask=ask,
        spread_pct=spread_pct,
        quote_age_seconds=quote_age,
        bars_available=bars_available,
        extra_features=extra,
        level=level,
        component=component,
    )
    return ParsedSnapshot(snapshot=snapshot, source_kind="alpaca_equity_scan", should_predict=True)


def _parse_coinbase_message(
    *,
    source_file: Path,
    source_line: int,
    raw_line: str,
    created_at_utc: str,
    level: str,
    component: str,
    message: str,
) -> ParsedSnapshot | None:
    signal = SIGNAL_RE.search(message)
    if signal:
        body = signal.group("body")
        fields = _parse_key_values(body)
        price = _extract_price(fields)
        spread_pct = _safe_float(fields.get("spread"))
        snapshot = _snapshot_from_log(
            broker="coinbase",
            asset_class="crypto",
            symbol=signal.group("symbol"),
            strategy=signal.group("strategy"),
            source_file=source_file,
            source_line=source_line,
            raw_line=raw_line,
            created_at_utc=created_at_utc,
            source_kind="coinbase_signal",
            market_data_status="valid",
            skip_reason="",
            price=price,
            spread_pct=spread_pct,
            bars_available=1,
            extra_features={"parsed_fields": fields, "regime": _extract_regime(body)},
            level=level,
            component=component,
        )
        return ParsedSnapshot(
            snapshot=snapshot,
            source_kind="coinbase_signal",
            should_predict=True,
            would_trade=True,
        )

    order = ORDER_PLACED_RE.search(message)
    if order:
        snapshot = _snapshot_from_log(
            broker="coinbase",
            asset_class="crypto",
            symbol=order.group("symbol"),
            strategy="order_observed",
            source_file=source_file,
            source_line=source_line,
            raw_line=raw_line,
            created_at_utc=created_at_utc,
            source_kind="coinbase_order_placed",
            market_data_status="unknown",
            skip_reason="",
            extra_features={"side": order.group("side").lower()},
            level=level,
            component=component,
        )
        return ParsedSnapshot(
            snapshot=snapshot,
            source_kind="coinbase_order_placed",
            should_predict=True,
            live_trade_taken=True,
        )

    exit_trigger = EXIT_TRIGGER_RE.search(message)
    if exit_trigger:
        body = exit_trigger.group("body")
        fields = _parse_key_values(body)
        snapshot = _snapshot_from_log(
            broker="coinbase",
            asset_class="crypto",
            symbol=exit_trigger.group("symbol"),
            strategy="position_manager",
            source_file=source_file,
            source_line=source_line,
            raw_line=raw_line,
            created_at_utc=created_at_utc,
            source_kind="coinbase_exit_trigger",
            market_data_status="valid",
            skip_reason="",
            price=_extract_price(fields),
            bars_available=1,
            extra_features={"parsed_fields": fields},
            level=level,
            component=component,
        )
        return ParsedSnapshot(
            snapshot=snapshot,
            source_kind="coinbase_exit_trigger",
            should_predict=True,
            live_trade_taken=True,
        )

    journal = JOURNAL_RE.search(message)
    if journal and "/" in journal.group("symbol"):
        event = journal.group("event").lower()
        rest = journal.group("rest")
        fields = _parse_key_values(rest)
        snapshot = _snapshot_from_log(
            broker="coinbase",
            asset_class="crypto",
            symbol=journal.group("symbol"),
            strategy=_first_token(rest) or event,
            source_file=source_file,
            source_line=source_line,
            raw_line=raw_line,
            created_at_utc=created_at_utc,
            source_kind=f"coinbase_journal_{event}",
            market_data_status="unknown",
            skip_reason=rest if event == "skip" else "",
            price=_extract_price(fields),
            bars_available=1 if _extract_price(fields) else None,
            extra_features={"parsed_fields": fields, "event": event},
            level=level,
            component=component,
        )
        return ParsedSnapshot(
            snapshot=snapshot,
            source_kind=f"coinbase_journal_{event}",
            should_predict=True,
            live_trade_taken=event in {"exit", "buy", "sell", "fill", "entry"},
        )

    scan = CRYPTO_SCAN_RE.search(message)
    if scan:
        symbol = scan.group("symbol")
        body = scan.group("body")
        if body.startswith("regime="):
            regime = _extract_regime(body)
            market_status = "valid" if regime else "unknown"
            skip_reason = "dead_chop" if regime == "dead_chop" else ""
            source_kind = "coinbase_regime_scan"
            strategy = "scan_all"
        else:
            market_status, skip_reason, _bars = _market_status_from_body(body)
            source_kind = "coinbase_scan_skip"
            strategy = _strategy_from_crypto_body(body)
        fields = _parse_key_values(body)
        snapshot = _snapshot_from_log(
            broker="coinbase",
            asset_class="crypto",
            symbol=symbol,
            strategy=strategy,
            source_file=source_file,
            source_line=source_line,
            raw_line=raw_line,
            created_at_utc=created_at_utc,
            source_kind=source_kind,
            market_data_status=market_status,
            skip_reason=skip_reason,
            price=_extract_price(fields),
            spread_pct=_safe_float(fields.get("spread")),
            bars_available=1 if _extract_price(fields) else None,
            extra_features={
                "parsed_fields": fields,
                "regime": _extract_regime(body),
            },
            level=level,
            component=component,
        )
        return ParsedSnapshot(snapshot=snapshot, source_kind=source_kind, should_predict=True)

    complete = COMPLETE_RE.search(message)
    if complete:
        return None
    return None


def _extract_regime(text: str) -> str:
    match = re.search(r"\bregime=([A-Za-z0-9_]+)", text)
    return match.group(1) if match else ""


def _first_token(text: str) -> str:
    parts = [part.strip() for part in text.split("|")]
    if not parts:
        return ""
    token = parts[0].split()[0] if parts[0].split() else ""
    return token if token else ""


def _strategy_from_crypto_body(body: str) -> str:
    token = body.split("|", 1)[0].strip().split(" ", 1)[0]
    return token if token and token not in {"regime=dead_chop", "regime=range"} else "scan_all"


def parse_log_line(
    raw_line: str,
    *,
    broker: str,
    source_file: Path,
    source_line: int,
    since: datetime | None = None,
) -> ParsedSnapshot | None:
    match = LOG_RE.match(raw_line.rstrip("\n"))
    if not match:
        return None
    ts = _parse_log_timestamp(match.group("ts"))
    if since and ts < since:
        return None
    created_at_utc = _iso(ts)
    message = match.group("message")
    kwargs = {
        "source_file": source_file,
        "source_line": source_line,
        "raw_line": raw_line.rstrip("\n"),
        "created_at_utc": created_at_utc,
        "level": match.group("level").strip(),
        "component": match.group("component").strip(),
        "message": message,
    }
    if broker == "alpaca":
        return _parse_alpaca_message(**kwargs)
    if broker == "coinbase":
        return _parse_coinbase_message(**kwargs)
    return None


def _prediction_filter(parsed: ParsedSnapshot) -> Iterable[dict[str, Any]]:
    snapshot = parsed.snapshot
    predictions = generate_baseline_predictions(
        {
            "features_json": json.dumps(snapshot.features),
            "spread_pct": snapshot.spread_pct,
            "quote_age_seconds": snapshot.quote_age_seconds,
            "bars_available": snapshot.bars_available,
            "market_data_status": snapshot.market_data_status,
            "price": snapshot.price,
            "bid": snapshot.bid,
            "ask": snapshot.ask,
        }
    )
    has_price = snapshot.price is not None and snapshot.price > 0
    has_bars = snapshot.bars_available is not None and snapshot.bars_available > 0
    status = snapshot.market_data_status
    directional_ok = has_price and has_bars and status not in {
        "invalid_quote",
        "stale_quote",
        "no_bars",
        "spread_too_wide",
    }
    for prediction in predictions:
        prediction_type = prediction["prediction_type"]
        if prediction_type.startswith("return_direction_") and not directional_ok:
            continue
        if prediction_type == "would_hit_take_profit_before_stop" and not directional_ok:
            continue
        yield prediction


def _snapshot_exists(snapshot_id: str, db_path: str | Path | None) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM shadow_feature_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    return row is not None


def _prediction_exists(prediction_id: str, db_path: str | Path | None) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM shadow_predictions WHERE prediction_id = ?",
            (prediction_id,),
        ).fetchone()
    return row is not None


def _open_readonly_db(db_path: str | Path | None) -> sqlite3.Connection | None:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return None
    conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _snapshot_exists_conn(conn: sqlite3.Connection, snapshot_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM shadow_feature_snapshots WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    return row is not None


def _prediction_exists_conn(conn: sqlite3.Connection, prediction_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM shadow_predictions WHERE prediction_id = ?",
        (prediction_id,),
    ).fetchone()
    return row is not None


def _prediction_id(snapshot_id: str, prediction: dict[str, Any]) -> str:
    return _stable_id(
        "pred",
        snapshot_id,
        prediction["prediction_type"],
        prediction["model_name"],
        prediction.get("model_version", ""),
        prediction["horizon_minutes"],
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_state_positions(
    *,
    broker: str,
    state_root: Path,
    since: datetime | None,
) -> list[ParsedSnapshot]:
    rel = Path(broker) / DEFAULT_STATE[broker][0]
    path = state_root / rel
    data = _read_json(path)
    saved_at = data.get("saved_at") or ""
    if not saved_at:
        return []
    try:
        saved_dt = datetime.fromisoformat(saved_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        saved_dt = datetime.now(timezone.utc)
    if since and saved_dt < since:
        return []
    positions = data.get("positions") or {}
    if not isinstance(positions, dict):
        return []
    parsed: list[ParsedSnapshot] = []
    for symbol, position in positions.items():
        if not isinstance(position, dict):
            continue
        raw = json.dumps(
            {
                "symbol": symbol,
                "strategy": position.get("strategy"),
                "order_status": position.get("order_status"),
                "notional": position.get("notional"),
                "entry_price": position.get("entry_price"),
            },
            sort_keys=True,
            default=str,
        )
        asset_class = position.get("asset_class") or ("crypto" if "/" in symbol else "equity")
        snapshot = _snapshot_from_log(
            broker=broker,
            asset_class=str(asset_class),
            symbol=symbol,
            strategy=str(position.get("strategy") or "state_position"),
            source_file=rel,
            source_line=0,
            raw_line=raw,
            created_at_utc=_iso(saved_dt),
            source_kind="state_open_position",
            market_data_status="unknown",
            skip_reason="",
            price=_safe_float(position.get("entry_price")),
            bars_available=None,
            extra_features={
                "ingestion_source": f"state:{rel.as_posix()}",
                "notional": _safe_float(position.get("notional")),
                "qty": _safe_float(position.get("qty")),
                "order_status": position.get("order_status"),
            },
        )
        parsed.append(
            ParsedSnapshot(
                snapshot=snapshot,
                source_kind="state_open_position",
                should_predict=True,
                live_trade_taken=position.get("order_status") == "filled",
            )
        )
    return parsed


def _runtime_sources(broker: str, runtime_root: Path) -> list[Path]:
    return [runtime_root / name for name in DEFAULT_RUNTIME.get(broker, ())]


def discover_sources(
    *,
    broker: str,
    logs_root: Path,
    runtime_root: Path,
    state_root: Path,
) -> tuple[list[tuple[str, Path]], list[Path], list[Path]]:
    brokers = ("alpaca", "coinbase") if broker == "all" else (broker,)
    log_sources: list[tuple[str, Path]] = []
    runtime_sources: list[Path] = []
    state_sources: list[Path] = []
    for item in brokers:
        for name in DEFAULT_LOGS.get(item, ()):
            log_sources.append((item, logs_root / name))
        runtime_sources.extend(_runtime_sources(item, runtime_root))
        state_sources.append(state_root / item / DEFAULT_STATE[item][0])
    return log_sources, runtime_sources, state_sources


def collect_snapshots(
    *,
    broker: str,
    logs_root: Path,
    runtime_root: Path,
    state_root: Path,
    since: datetime | None,
) -> tuple[list[ParsedSnapshot], dict[str, int]]:
    log_sources, runtime_sources, state_sources = discover_sources(
        broker=broker,
        logs_root=logs_root,
        runtime_root=runtime_root,
        state_root=state_root,
    )
    counts = {
        "log_files_seen": 0,
        "runtime_files_seen": 0,
        "state_files_seen": 0,
        "lines_seen": 0,
        "lines_parsed": 0,
    }
    parsed: list[ParsedSnapshot] = []
    for source_broker, path in log_sources:
        if not path.exists():
            continue
        counts["log_files_seen"] += 1
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    counts["lines_seen"] += 1
                    item = parse_log_line(
                        raw_line,
                        broker=source_broker,
                        source_file=rel,
                        source_line=line_number,
                        since=since,
                    )
                    if item is None:
                        continue
                    counts["lines_parsed"] += 1
                    parsed.append(item)
        except OSError:
            continue
    for path in runtime_sources:
        if path.exists():
            counts["runtime_files_seen"] += 1
            _read_json(path)
    target_brokers = ("alpaca", "coinbase") if broker == "all" else (broker,)
    for target_broker in target_brokers:
        state_path = state_root / target_broker / DEFAULT_STATE[target_broker][0]
        if state_path.exists():
            counts["state_files_seen"] += 1
        parsed.extend(
            _parse_state_positions(
                broker=target_broker,
                state_root=state_root,
                since=since,
            )
        )
    return parsed, counts


def ingest_snapshots(
    parsed: list[ParsedSnapshot],
    *,
    db_path: str | Path | None,
    dry_run: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "parsed_snapshots": len(parsed),
        "would_create_predictions": 0,
        "would_insert_snapshots": 0,
        "inserted_snapshots": 0,
        "existing_snapshots": 0,
        "created_predictions": 0,
        "existing_predictions": 0,
        "would_create_prospective_predictions": 0,
        "created_prospective_predictions": 0,
        "existing_prospective_predictions": 0,
        "prospective_snapshots_with_context": 0,
        "prospective_snapshots_skipped": 0,
        "prospective_skipped_existing_snapshots": 0,
        "prospective_by_model": {},
        "prospective_skip_reasons": {},
        "by_broker": {},
        "by_source_kind": {},
    }
    readonly_conn = _open_readonly_db(db_path) if dry_run else None
    try:
        for item in parsed:
            broker = item.snapshot.broker
            summary["by_broker"][broker] = summary["by_broker"].get(broker, 0) + 1
            summary["by_source_kind"][item.source_kind] = summary["by_source_kind"].get(item.source_kind, 0) + 1
            if dry_run and item.should_predict:
                snapshot_exists = (
                    _snapshot_exists_conn(readonly_conn, item.snapshot.snapshot_id)
                    if readonly_conn is not None
                    else False
                )
                if snapshot_exists:
                    summary["existing_snapshots"] += 1
                    summary["prospective_skipped_existing_snapshots"] += 1
                    for prediction in _prediction_filter(item):
                        prediction_id = _prediction_id(item.snapshot.snapshot_id, prediction)
                        if readonly_conn is not None and _prediction_exists_conn(
                            readonly_conn, prediction_id
                        ):
                            summary["existing_predictions"] += 1
                        else:
                            summary["would_create_predictions"] += 1
                    continue

                summary["would_insert_snapshots"] += 1
                summary["would_create_predictions"] += sum(1 for _ in _prediction_filter(item))
                snapshot_row = snapshot_row_from_feature_snapshot(item.snapshot)
                if readonly_conn is not None:
                    rows, skip_reason = prediction_rows_for_snapshot_with_db_context(
                        readonly_conn,
                        snapshot=snapshot_row,
                        generation_source="shadow_ingest_logs",
                    )
                else:
                    rows, skip_reason = prediction_rows_for_snapshot(
                        snapshot=snapshot_row,
                        prior_prices=(),
                        generation_source="shadow_ingest_logs",
                    )
                summary["would_create_prospective_predictions"] += len(rows)
                if rows:
                    summary["prospective_snapshots_with_context"] += 1
                    for row in rows:
                        model_name = row["model_name"]
                        summary["prospective_by_model"][model_name] = (
                            summary["prospective_by_model"].get(model_name, 0) + 1
                        )
                elif skip_reason:
                    summary["prospective_snapshots_skipped"] += 1
                    summary["prospective_skip_reasons"][skip_reason] = (
                        summary["prospective_skip_reasons"].get(skip_reason, 0) + 1
                    )
    finally:
        if readonly_conn is not None:
            readonly_conn.close()

    if dry_run:
        return summary

    init_db(db_path)
    for item in parsed:
        exists = _snapshot_exists(item.snapshot.snapshot_id, db_path)
        if exists:
            summary["existing_snapshots"] += 1
        else:
            summary["inserted_snapshots"] += 1
        snapshot_id = record_feature_snapshot(item.snapshot, db_path=db_path)
        if not item.should_predict:
            continue
        if exists:
            summary["prospective_skipped_existing_snapshots"] += 1
        else:
            prospective = generate_prospective_predictions_for_snapshot(
                snapshot_id,
                db_path=db_path,
                generation_source="shadow_ingest_logs",
            )
            summary["created_prospective_predictions"] += int(prospective["inserted"])
            summary["existing_prospective_predictions"] += int(prospective["existing"])
            summary["prospective_snapshots_with_context"] += int(
                prospective["snapshots_with_context"]
            )
            summary["prospective_snapshots_skipped"] += int(prospective["snapshots_skipped"])
            for model_name, count in prospective["by_model"].items():
                summary["prospective_by_model"][model_name] = (
                    summary["prospective_by_model"].get(model_name, 0) + int(count)
                )
            for reason, count in prospective["skip_reasons"].items():
                summary["prospective_skip_reasons"][reason] = (
                    summary["prospective_skip_reasons"].get(reason, 0) + int(count)
                )
        for prediction in _prediction_filter(item):
            prediction["prediction_id"] = _prediction_id(snapshot_id, prediction)
            already = _prediction_exists(prediction["prediction_id"], db_path)
            if already:
                summary["existing_predictions"] += 1
            else:
                summary["created_predictions"] += 1
            record_prediction(
                snapshot_id,
                prediction,
                db_path=db_path,
                would_trade=item.would_trade,
                live_trade_taken=item.live_trade_taken,
            )
    return summary


def _format_counts(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["  none"]
    return [f"  {key}: {counts[key]}" for key in sorted(counts)]


def build_output(
    *,
    summary: dict[str, Any],
    source_counts: dict[str, int],
    dry_run: bool,
    parsed: list[ParsedSnapshot],
) -> str:
    lines = [
        "Shadow ingest logs",
        f"Mode: {'dry-run' if dry_run else 'write'}",
        f"Parsed snapshots: {summary['parsed_snapshots']}",
        f"Would create predictions: {summary['would_create_predictions']}" if dry_run else None,
        f"Would insert snapshots: {summary['would_insert_snapshots']}" if dry_run else None,
        f"Inserted snapshots: {summary['inserted_snapshots']}",
        f"Existing snapshots: {summary['existing_snapshots']}",
        f"Created predictions: {summary['created_predictions']}",
        f"Existing predictions: {summary['existing_predictions']}",
        (
            f"Would create prospective shadow predictions: {summary['would_create_prospective_predictions']}"
            if dry_run
            else None
        ),
        f"Created prospective shadow predictions: {summary['created_prospective_predictions']}",
        f"Existing prospective shadow predictions: {summary['existing_prospective_predictions']}",
        f"Prospective snapshots with t0/prior context: {summary['prospective_snapshots_with_context']}",
        f"Prospective snapshots skipped: {summary['prospective_snapshots_skipped']}",
        f"Prospective generation skipped for existing snapshots: {summary['prospective_skipped_existing_snapshots']}",
        "",
        "Source files seen:",
        f"  logs: {source_counts['log_files_seen']}",
        f"  runtime: {source_counts['runtime_files_seen']}",
        f"  state: {source_counts['state_files_seen']}",
        f"  log_lines_seen: {source_counts['lines_seen']}",
        f"  log_lines_parsed: {source_counts['lines_parsed']}",
        "",
        "Parsed by broker:",
        *_format_counts(summary["by_broker"]),
        "",
        "Parsed by source kind:",
        *_format_counts(summary["by_source_kind"]),
        "",
        "Prospective shadow predictions by model:",
        *_format_counts(summary["prospective_by_model"]),
        "",
        "Prospective shadow skip reasons:",
        *_format_counts(summary["prospective_skip_reasons"]),
    ]
    lines = [line for line in lines if line is not None]
    if dry_run and parsed:
        lines.extend(["", "Sample redacted source lines:"])
        for item in parsed[:5]:
            raw = item.snapshot.features.get("raw_line_redacted", "")
            lines.append(f"  {raw}")
    lines.append("")
    lines.append("Recommendation: advisory only; not used for live trading")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="Local date or timestamp lower bound")
    parser.add_argument("--broker", default="all", choices=["all", "alpaca", "coinbase"])
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    parser.add_argument("--logs-root", default=str(ROOT / "logs"))
    parser.add_argument("--runtime-root", default=str(ROOT / "runtime"))
    parser.add_argument("--state-root", default=str(ROOT / "state"))
    args = parser.parse_args()

    since = _parse_since(args.since)
    parsed, source_counts = collect_snapshots(
        broker=args.broker,
        logs_root=Path(args.logs_root),
        runtime_root=Path(args.runtime_root),
        state_root=Path(args.state_root),
        since=since,
    )
    summary = ingest_snapshots(parsed, db_path=args.db, dry_run=args.dry_run)
    print(
        build_output(
            summary=summary,
            source_counts=source_counts,
            dry_run=args.dry_run,
            parsed=parsed,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
