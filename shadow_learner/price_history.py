"""Manual/read-only price-history storage for shadow outcome labeling."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.redact import redact_text

from .outcome_labeler import PriceObservation
from .schema import connect, init_db, json_dumps, utc_now


@dataclass(frozen=True)
class PricePoint:
    source: str
    symbol: str
    asset_class: str
    timestamp_utc: str
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    timeframe: str = "1m"
    payload: dict[str, Any] = field(default_factory=dict)
    price_id: str = ""


def stable_price_id(source: str, symbol: str, timeframe: str, timestamp_utc: str) -> str:
    digest = hashlib.sha256(
        f"{source}|{symbol}|{timeframe}|{timestamp_utc}".encode("utf-8")
    ).hexdigest()[:32]
    return f"price_{digest}"


def parse_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_asset_class(symbol: str) -> str:
    return "crypto" if "/" in symbol else "equity"


def price_point_from_mapping(row: dict[str, Any]) -> tuple[PricePoint | None, str]:
    source = str(row.get("source") or "manual").strip()
    symbol = str(row.get("symbol") or "").strip().upper()
    timestamp_raw = row.get("timestamp_utc") or row.get("time") or row.get("ts")
    close = _safe_float(row.get("close", row.get("price", row.get("last"))))
    if not source:
        return None, "missing source"
    if not symbol:
        return None, "missing symbol"
    if not timestamp_raw:
        return None, "missing timestamp_utc"
    if close is None or close <= 0:
        return None, "missing/invalid close"
    try:
        timestamp_utc = parse_timestamp(str(timestamp_raw))
    except ValueError:
        return None, "invalid timestamp_utc"

    open_price = _safe_float(row.get("open"))
    high = _safe_float(row.get("high"))
    low = _safe_float(row.get("low"))
    volume = _safe_float(row.get("volume"))
    if open_price is None:
        open_price = close
    if high is None:
        high = max(open_price, close)
    if low is None:
        low = min(open_price, close)
    high = max(high, open_price, close)
    low = min(low, open_price, close)
    timeframe = str(row.get("timeframe") or "1m").strip() or "1m"
    asset_class = str(row.get("asset_class") or _infer_asset_class(symbol)).strip()
    point = PricePoint(
        price_id=str(row.get("price_id") or ""),
        source=source,
        symbol=symbol,
        asset_class=asset_class,
        timestamp_utc=timestamp_utc,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        timeframe=timeframe,
        payload={
            key: value
            for key, value in row.items()
            if key
            not in {
                "source",
                "symbol",
                "asset_class",
                "timestamp_utc",
                "time",
                "ts",
                "open",
                "high",
                "low",
                "close",
                "price",
                "last",
                "volume",
                "timeframe",
                "price_id",
            }
        },
    )
    return point, ""


def read_price_file(path: str | Path) -> tuple[list[PricePoint], list[str]]:
    price_path = Path(path)
    suffix = price_path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(price_path)
    return _read_json_or_jsonl(price_path)


def _read_json_or_jsonl(path: Path) -> tuple[list[PricePoint], list[str]]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return [], []
    rows: list[Any]
    try:
        parsed = json.loads(stripped)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        rows = []
        errors: list[str] = []
        for line_number, line in enumerate(stripped.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                errors.append(f"line {line_number}: invalid json")
        points, validation_errors = _rows_to_points(rows)
        return points, errors + validation_errors
    return _rows_to_points(rows)


def _read_csv(path: Path) -> tuple[list[PricePoint], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return _rows_to_points(rows)


def _rows_to_points(rows: Iterable[Any]) -> tuple[list[PricePoint], list[str]]:
    points: list[PricePoint] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {index}: expected object")
            continue
        point, error = price_point_from_mapping(row)
        if error:
            errors.append(f"row {index}: {redact_text(error)}")
            continue
        assert point is not None
        points.append(point)
    return points, errors


def record_price_points(
    points: Iterable[PricePoint],
    *,
    db_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    summary = {
        "seen": 0,
        "inserted": 0,
        "existing": 0,
        "by_source": {},
        "by_symbol": {},
        "by_timeframe": {},
    }
    point_list = list(points)
    summary["seen"] = len(point_list)
    for point in point_list:
        summary["by_source"][point.source] = summary["by_source"].get(point.source, 0) + 1
        summary["by_symbol"][point.symbol] = summary["by_symbol"].get(point.symbol, 0) + 1
        summary["by_timeframe"][point.timeframe] = summary["by_timeframe"].get(point.timeframe, 0) + 1
    if dry_run:
        return summary
    init_db(db_path)
    with connect(db_path) as conn:
        for point in point_list:
            price_id = point.price_id or stable_price_id(
                point.source, point.symbol, point.timeframe, point.timestamp_utc
            )
            exists = conn.execute(
                """
                SELECT 1 FROM shadow_price_points
                WHERE source = ? AND symbol = ? AND timeframe = ? AND timestamp_utc = ?
                """,
                (point.source, point.symbol, point.timeframe, point.timestamp_utc),
            ).fetchone()
            if exists:
                summary["existing"] += 1
            else:
                summary["inserted"] += 1
            conn.execute(
                """
                INSERT OR IGNORE INTO shadow_price_points (
                    price_id, source, symbol, asset_class, timestamp_utc,
                    open, high, low, close, volume, timeframe, ingested_at_utc,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    price_id,
                    point.source,
                    point.symbol,
                    point.asset_class,
                    point.timestamp_utc,
                    point.open,
                    point.high,
                    point.low,
                    point.close,
                    point.volume,
                    point.timeframe,
                    utc_now(),
                    json_dumps(point.payload),
                ),
            )
    return summary


def fetch_price_observations(
    *,
    db_path: str | Path | None = None,
    since_utc: str | None = None,
    symbol: str | None = None,
) -> list[PriceObservation]:
    init_db(db_path)
    clauses: list[str] = []
    params: list[Any] = []
    if since_utc:
        clauses.append("timestamp_utc >= ?")
        params.append(since_utc)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM shadow_price_points
            {where}
            ORDER BY symbol, timestamp_utc
            """,
            params,
        ).fetchall()
    return [
        PriceObservation(
            symbol=row["symbol"],
            timestamp_utc=row["timestamp_utc"],
            price=float(row["close"]),
            source=f"price_history:{row['source']}",
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            timeframe=row["timeframe"],
        )
        for row in rows
    ]


def count_price_points(db_path: str | Path | None = None) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM shadow_price_points").fetchone()[0])
