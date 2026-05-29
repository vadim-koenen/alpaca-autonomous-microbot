"""Unauthenticated public candle backfill for shadow price history."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.redact import redact_text

from .price_history import PricePoint, record_price_points
from .schema import connect, init_db, resolve_db_path

COINBASE_PUBLIC_CANDLES_SOURCE = "coinbase_public_candles"
COINBASE_EXCHANGE_BASE_URL = "https://api.exchange.coinbase.com"
MAX_COINBASE_CANDLES = 300
ALLOWED_GRANULARITIES = {60, 300, 900, 3600, 21600, 86400}


@dataclass(frozen=True)
class BackfillWindow:
    start_utc: str
    end_utc: str


def product_id_for_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "-")


def symbol_for_product_id(product_id: str) -> str:
    return product_id.strip().upper().replace("-", "/")


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("-", "/")


def parse_utc(value: str) -> datetime:
    if "T" in value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def infer_needed_window(
    *,
    symbol: str,
    since_utc: str,
    db_path: str | Path | None = None,
    fallback_hours: int = 24,
    create_db: bool = True,
) -> BackfillWindow:
    """Infer a compact backfill window from shadow prediction timestamps."""
    start = parse_utc(since_utc)
    end = start + timedelta(hours=fallback_hours)
    db_file = resolve_db_path(db_path)
    if create_db:
        init_db(db_file)
    elif not db_file.exists():
        return BackfillWindow(start_utc=iso_utc(start), end_utc=iso_utc(end))
    try:
        with connect(db_file) as conn:
            row = conn.execute(
                """
                SELECT MIN(created_at_utc) AS min_created,
                       MAX(datetime(replace(created_at_utc, 'Z', ''), '+' || horizon_minutes || ' minutes')) AS max_end
                FROM shadow_predictions
                WHERE symbol = ? AND created_at_utc >= ?
                """,
                (symbol, since_utc),
            ).fetchone()
    except sqlite3.Error:
        if create_db:
            raise
        return BackfillWindow(start_utc=iso_utc(start), end_utc=iso_utc(end))
    if row and row["min_created"]:
        start = min(start, parse_utc(row["min_created"]))
    if row and row["max_end"]:
        end = parse_utc(str(row["max_end"]).replace(" ", "T") + "Z")
    if end <= start:
        end = start + timedelta(hours=fallback_hours)
    return BackfillWindow(start_utc=iso_utc(start), end_utc=iso_utc(end))


def infer_shadow_crypto_symbols(
    *,
    since_utc: str,
    db_path: str | Path | None = None,
    create_db: bool = True,
) -> list[str]:
    """Return crypto symbols that already exist in shadow predictions/snapshots."""
    db_file = resolve_db_path(db_path)
    if create_db:
        init_db(db_file)
    elif not db_file.exists():
        return []
    try:
        with connect(db_file) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT symbol
                FROM shadow_predictions
                WHERE asset_class = 'crypto' AND created_at_utc >= ?
                UNION
                SELECT DISTINCT symbol
                FROM shadow_feature_snapshots
                WHERE asset_class = 'crypto' AND created_at_utc >= ?
                """,
                (since_utc, since_utc),
            ).fetchall()
    except sqlite3.Error:
        if create_db:
            raise
        return []
    symbols = {
        normalize_symbol(row["symbol"])
        for row in rows
        if row["symbol"] and "/" in normalize_symbol(row["symbol"])
    }
    return sorted(symbols)


def chunk_windows(start: datetime, end: datetime, granularity: int) -> list[tuple[datetime, datetime]]:
    step = timedelta(seconds=granularity * MAX_COINBASE_CANDLES)
    chunks = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + step, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return chunks


def build_coinbase_candles_url(product_id: str, *, start: datetime, end: datetime, granularity: int) -> str:
    query = urllib.parse.urlencode(
        {
            "start": iso_utc(start),
            "end": iso_utc(end),
            "granularity": granularity,
        }
    )
    return f"{COINBASE_EXCHANGE_BASE_URL}/products/{urllib.parse.quote(product_id)}/candles?{query}"


def fetch_coinbase_candles(
    product_id: str,
    *,
    start: datetime,
    end: datetime,
    granularity: int,
    timeout_seconds: float = 8.0,
) -> tuple[list[Any], str]:
    url = build_coinbase_candles_url(product_id, start=start, end=end, granularity=granularity)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "shadow-learner-public-price-backfill/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(1_000_000)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [], redact_text(f"{type(exc).__name__}: {exc}")
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], redact_text(f"parse_error: {type(exc).__name__}")
    if not isinstance(parsed, list):
        return [], "unexpected response shape"
    return parsed, ""


def normalize_coinbase_candles(
    candles: list[Any],
    *,
    symbol: str,
    granularity: int,
    source: str = COINBASE_PUBLIC_CANDLES_SOURCE,
) -> tuple[list[PricePoint], list[str]]:
    points: list[PricePoint] = []
    errors: list[str] = []
    for index, candle in enumerate(candles, start=1):
        if not isinstance(candle, list) or len(candle) < 6:
            errors.append(f"row {index}: unexpected candle shape")
            continue
        try:
            ts, low, high, open_price, close, volume = candle[:6]
            timestamp = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            point = PricePoint(
                source=source,
                symbol=symbol,
                asset_class="crypto" if "/" in symbol else "equity",
                timestamp_utc=iso_utc(timestamp),
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
                timeframe=f"{granularity}s",
                payload={"product_id": product_id_for_symbol(symbol)},
            )
        except (TypeError, ValueError, OSError) as exc:
            errors.append(f"row {index}: {type(exc).__name__}")
            continue
        points.append(point)
    return sorted(points, key=lambda point: point.timestamp_utc), errors


def backfill_public_prices(
    *,
    symbol: str,
    since_utc: str,
    granularity: int,
    db_path: str | Path | None = None,
    dry_run: bool = False,
    timeout_seconds: float = 8.0,
    fetcher: Callable[..., tuple[list[Any], str]] | None = None,
) -> dict[str, Any]:
    if granularity not in ALLOWED_GRANULARITIES:
        return {
            "symbol": symbol,
            "product_id": product_id_for_symbol(symbol),
            "granularity": granularity,
            "fetched_candles": 0,
            "normalized_points": 0,
            "inserted": 0,
            "existing": 0,
            "errors": [f"unsupported granularity: {granularity}"],
            "dry_run": dry_run,
            "window": {"start_utc": since_utc, "end_utc": since_utc},
        }
    product_id = product_id_for_symbol(symbol)
    window = infer_needed_window(
        symbol=symbol,
        since_utc=since_utc,
        db_path=db_path,
        create_db=not dry_run,
    )
    start = parse_utc(window.start_utc)
    end = parse_utc(window.end_utc)
    fetch = fetcher or fetch_coinbase_candles
    all_points: list[PricePoint] = []
    errors: list[str] = []
    fetched_candles = 0
    for chunk_start, chunk_end in chunk_windows(start, end, granularity):
        raw, error = fetch(
            product_id,
            start=chunk_start,
            end=chunk_end,
            granularity=granularity,
            timeout_seconds=timeout_seconds,
        )
        if error:
            errors.append(redact_text(error))
            continue
        fetched_candles += len(raw)
        points, normalize_errors = normalize_coinbase_candles(
            raw,
            symbol=symbol,
            granularity=granularity,
        )
        all_points.extend(points)
        errors.extend(redact_text(error) for error in normalize_errors)
    summary = record_price_points(all_points, db_path=db_path, dry_run=dry_run)
    return {
        "symbol": symbol,
        "product_id": product_id,
        "granularity": granularity,
        "fetched_candles": fetched_candles,
        "normalized_points": len(all_points),
        "inserted": summary["inserted"],
        "existing": summary["existing"],
        "errors": errors,
        "dry_run": dry_run,
        "window": {"start_utc": window.start_utc, "end_utc": window.end_utc},
        "by_source": summary["by_source"],
        "by_symbol": summary["by_symbol"],
        "by_timeframe": summary["by_timeframe"],
    }


def backfill_public_prices_for_symbols(
    *,
    symbols: list[str] | tuple[str, ...] | None,
    since_utc: str,
    granularity: int,
    db_path: str | Path | None = None,
    dry_run: bool = False,
    timeout_seconds: float = 8.0,
    from_predictions: bool = False,
    fetcher: Callable[..., tuple[list[Any], str]] | None = None,
) -> dict[str, Any]:
    """Backfill public candles for shadow-known crypto symbols only."""
    available_symbols = infer_shadow_crypto_symbols(
        since_utc=since_utc,
        db_path=db_path,
        create_db=not dry_run,
    )
    available = set(available_symbols)
    requested = available_symbols if from_predictions else [normalize_symbol(item) for item in (symbols or [])]
    deduped_requested = list(dict.fromkeys(symbol for symbol in requested if symbol))
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    totals = {
        "fetched_candles": 0,
        "normalized_points": 0,
        "inserted": 0,
        "existing": 0,
    }
    for symbol in deduped_requested:
        if symbol not in available:
            skipped.append(
                {
                    "symbol": symbol,
                    "reason": "no shadow crypto predictions/snapshots since requested timestamp",
                }
            )
            continue
        result = backfill_public_prices(
            symbol=symbol,
            since_utc=since_utc,
            granularity=granularity,
            db_path=db_path,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            fetcher=fetcher,
        )
        results.append(result)
        for key in totals:
            totals[key] += int(result.get(key, 0) or 0)
    return {
        "dry_run": dry_run,
        "from_predictions": from_predictions,
        "since_utc": since_utc,
        "granularity": granularity,
        "requested_symbols": deduped_requested,
        "available_symbols": available_symbols,
        "backfilled_symbols": [result["symbol"] for result in results],
        "skipped": skipped,
        "results": results,
        "totals": totals,
    }
