import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.event_store import EventStore
from utils import compute_config_hash


def test_event_store_initializes_schema_from_empty_path(tmp_path):
    db = tmp_path / "memory.sqlite3"
    store = EventStore(db)

    assert db.exists()
    with sqlite3.connect(db) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "events" in tables
    assert "orders" in tables
    assert "risk_decisions" in tables
    assert "incidents" in tables


def test_record_event_order_and_risk_decision(tmp_path):
    db = tmp_path / "memory.sqlite3"
    store = EventStore(db)
    run_id = store.start_run(
        bot_name="test_bot",
        broker="coinbase",
        mode="dry_run",
        asset_class="crypto",
        config_hash="abc123",
        payload={"config_file": "config_coinbase_crypto.yaml"},
    )

    assert run_id
    assert store.record_event(event_type="startup", payload={"ok": True})
    assert store.record_order(
        status="preview",
        client_order_id="cb-coinbase_probe-BTCUSD-buy-20260526T132500Z-entry-a1b2",
        intent_key="coinbase:coinbase_probe:crypto:BTC/USD:buy:entry",
        strategy="coinbase_probe",
        symbol="BTC/USD",
        asset_class="crypto",
        side="buy",
        purpose="entry",
        notional=0.5,
        qty=0.00001,
    )
    assert store.record_risk_decision(
        allowed=False,
        reason="total crypto exposure",
        strategy="coinbase_probe",
        symbol="BTC/USD",
        asset_class="crypto",
        requested_notional=0.5,
        current_exposure=6.18,
        projected_exposure=6.68,
        cap_name="crypto.max_total_crypto_exposure_usd",
        cap_value=4.0,
    )

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        order = conn.execute("SELECT * FROM orders").fetchone()
        risk = conn.execute("SELECT * FROM risk_decisions").fetchone()
        event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    assert event_count == 1
    assert order["client_order_id"].startswith("cb-")
    assert order["intent_key"] == "coinbase:coinbase_probe:crypto:BTC/USD:buy:entry"
    assert risk["allowed"] == 0
    assert risk["cap_value"] == pytest.approx(4.0)


def test_event_store_fail_safe_write_failure_does_not_crash(tmp_path):
    bad_path = tmp_path / "not_a_dir"
    bad_path.write_text("blocking directory creation")
    store = EventStore(bad_path / "db.sqlite3", fail_safe=True)

    assert store.record_event(event_type="startup") is False


def test_config_hash_excludes_secret_values():
    config = {
        "mode": "paper",
        "nested": {
            "api_key": "SHOULD_NOT_APPEAR",
            "secret_token": "ALSO_SECRET",
            "safe_value": "visible",
        },
    }

    digest, sanitized = compute_config_hash(config)
    rendered = str(sanitized)

    assert digest
    assert "SHOULD_NOT_APPEAR" not in rendered
    assert "ALSO_SECRET" not in rendered
    assert sanitized["nested"]["api_key"] == "<redacted>"
    assert sanitized["nested"]["safe_value"] == "visible"
