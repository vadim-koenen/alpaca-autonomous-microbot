"""Feature snapshot recording for read-only shadow learning."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import connect, init_db, json_dumps, new_id, utc_now

FEATURE_VERSION = "feature_snapshot_v0"


@dataclass(frozen=True)
class FeatureSnapshot:
    broker: str
    asset_class: str
    symbol: str
    strategy: str
    scan_id: str = ""
    price: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread_pct: float | None = None
    quote_age_seconds: float | None = None
    bars_available: int | None = None
    market_session: str = ""
    market_data_status: str = ""
    skip_reason: str = ""
    risk_block_reason: str = ""
    features: dict[str, Any] = field(default_factory=dict)
    created_at_utc: str = ""
    snapshot_id: str = ""


def record_feature_snapshot(
    snapshot: FeatureSnapshot,
    *,
    db_path: str | Path | None = None,
) -> str:
    """Persist one advisory feature snapshot and return its id.

    This writes only to shadow learner tables. It does not import or call risk,
    order, broker, or strategy modules.
    """
    init_db(db_path)
    snapshot_id = snapshot.snapshot_id or new_id("snap")
    created_at_utc = snapshot.created_at_utc or utc_now()
    features = {
        **snapshot.features,
        "feature_version": snapshot.features.get("feature_version", FEATURE_VERSION),
    }
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO shadow_feature_snapshots (
                snapshot_id, created_at_utc, broker, asset_class, symbol,
                strategy, scan_id, price, bid, ask, spread_pct,
                quote_age_seconds, bars_available, market_session,
                market_data_status, skip_reason, risk_block_reason,
                features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                created_at_utc,
                snapshot.broker,
                snapshot.asset_class,
                snapshot.symbol,
                snapshot.strategy,
                snapshot.scan_id,
                snapshot.price,
                snapshot.bid,
                snapshot.ask,
                snapshot.spread_pct,
                snapshot.quote_age_seconds,
                snapshot.bars_available,
                snapshot.market_session,
                snapshot.market_data_status,
                snapshot.skip_reason,
                snapshot.risk_block_reason,
                json_dumps(features),
            ),
        )
    return snapshot_id


def fetch_feature_snapshot(
    snapshot_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM shadow_feature_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    return dict(row) if row else None
