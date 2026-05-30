import csv
from pathlib import Path

import pytest

from coinbase_fill_logger import (
    COINBASE_FILL_FIELDS,
    COINBASE_FILL_SCHEMA_VERSION,
    append_coinbase_fill_row,
    build_coinbase_fill_row,
)


def read_rows(path: Path):
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_build_coinbase_fill_row_uses_deterministic_schema_and_defaults():
    row = build_coinbase_fill_row(
        source="unit-test",
        product_id="BTC-USD",
        side="sell",
        order_id="order-123",
        status="FILLED",
        captured_at_utc="2026-05-30T20:00:00Z",
    )

    assert tuple(row.keys()) == COINBASE_FILL_FIELDS
    assert row["schema_version"] == COINBASE_FILL_SCHEMA_VERSION
    assert row["broker"] == "coinbase"
    assert row["reconstruction_status"] == "unreconciled"
    assert row["product_id"] == "BTC-USD"
    assert row["side"] == "sell"


def test_append_coinbase_fill_row_creates_parent_header_and_row(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    row = build_coinbase_fill_row(
        source="unit-test",
        product_id="ETH-USD",
        side="buy",
        order_id="order-abc",
        status="FILLED",
        captured_at_utc="2026-05-30T20:01:00Z",
        filled_size="0.01",
        average_filled_price="3000.00",
        gross_quote_value="30.00",
        fee_amount="0.12",
        fee_currency="USD",
        net_quote_value="30.12",
    )

    returned_path = append_coinbase_fill_row(row, path=path)

    assert returned_path == path
    assert path.exists()
    rows = read_rows(path)
    assert len(rows) == 1
    assert rows[0]["order_id"] == "order-abc"
    assert rows[0]["fee_amount"] == "0.12"


def test_append_coinbase_fill_row_is_append_only_and_header_is_not_duplicated(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"

    row_1 = build_coinbase_fill_row(
        source="unit-test",
        product_id="SOL-USD",
        side="buy",
        order_id="order-1",
        status="FILLED",
        captured_at_utc="2026-05-30T20:02:00Z",
    )
    row_2 = build_coinbase_fill_row(
        source="unit-test",
        product_id="SOL-USD",
        side="sell",
        order_id="order-2",
        status="FILLED",
        captured_at_utc="2026-05-30T20:03:00Z",
    )

    append_coinbase_fill_row(row_1, path=path)
    append_coinbase_fill_row(row_2, path=path)

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    assert raw_lines[0].split(",") == list(COINBASE_FILL_FIELDS)
    assert sum(1 for line in raw_lines if line.startswith("schema_version,")) == 1

    rows = read_rows(path)
    assert [row["order_id"] for row in rows] == ["order-1", "order-2"]


def test_append_coinbase_fill_row_refuses_schema_mismatch(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    row = build_coinbase_fill_row(
        source="unit-test",
        product_id="BTC-USD",
        side="sell",
        order_id="order-123",
        status="FILLED",
    )
    row["unexpected"] = "do-not-log"

    with pytest.raises(ValueError, match="does not match schema"):
        append_coinbase_fill_row(row, path=path)

    assert not path.exists()


def test_append_coinbase_fill_row_refuses_existing_bad_header_without_truncating(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    path.parent.mkdir(parents=True)
    path.write_text("bad,header\nexisting,value\n", encoding="utf-8")

    row = build_coinbase_fill_row(
        source="unit-test",
        product_id="BTC-USD",
        side="sell",
        order_id="order-123",
        status="FILLED",
    )

    with pytest.raises(ValueError, match="header mismatch"):
        append_coinbase_fill_row(row, path=path)

    assert path.read_text(encoding="utf-8") == "bad,header\nexisting,value\n"


def test_raw_payloads_are_serialized_deterministically(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    row = build_coinbase_fill_row(
        source="unit-test",
        product_id="BTC-USD",
        side="sell",
        order_id="order-json",
        status="FILLED",
        raw_order_response_json={"z": 2, "a": 1},
        raw_fill_response_json=[{"b": 2, "a": 1}],
    )

    append_coinbase_fill_row(row, path=path)
    rows = read_rows(path)

    assert rows[0]["raw_order_response_json"] == '{"a":1,"z":2}'
    assert rows[0]["raw_fill_response_json"] == '[{"a":1,"b":2}]'
