# ADVISORY ONLY — tests for read-only diagnostics, no live trading calls.

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_sizing_execution_reconciliation_report.py"
spec = importlib.util.spec_from_file_location("coinbase_sizing_execution_reconciliation_report", MODULE_PATH)
report = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = report
spec.loader.exec_module(report)


def write_config(path: Path) -> None:
    path.write_text(
        """
coinbase_probe_notional_usd: 0.50
account:
  expected_starting_equity: 40.00
fees:
  maker_fee_pct: 0.006
  taker_fee_pct: 0.012
controlled_exploration:
  max_single_trade_notional_usd: 1.00
  max_total_exploration_exposure_usd: 6.00
  max_open_positions: 2
dynamic_sizing:
  position_size_pct: 0.025
  min_notional_usd: 1.00
  max_notional_usd: 25.00
""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_missing_journal_is_tolerated(tmp_path):
    config = tmp_path / "config.yaml"
    write_config(config)
    output = report.build_report(config, tmp_path / "missing.csv", tmp_path / "missing_path.csv")
    assert "Journal warning: missing:" in output
    assert "Completed reconstructed cycles: 0" in output


def test_empty_journal_is_tolerated(tmp_path):
    config = tmp_path / "config.yaml"
    journal = tmp_path / "journal.csv"
    write_config(config)
    journal.write_text("", encoding="utf-8")
    output = report.build_report(config, journal, tmp_path / "missing_path.csv")
    assert "No completed buy/sell cycles reconstructed" in output


def test_one_completed_cycle_with_usable_sell_fill(tmp_path):
    config = tmp_path / "config.yaml"
    journal = tmp_path / "journal.csv"
    write_config(config)
    write_csv(
        journal,
        [
            {
                "timestamp": "2026-05-30T10:00:00Z",
                "symbol": "BTC/USD",
                "side": "buy",
                "notional": "1.00",
                "fee_usd": "0.006",
                "reason": "entry",
            },
            {
                "timestamp": "2026-05-30T11:30:00Z",
                "symbol": "BTC/USD",
                "side": "sell",
                "notional": "1.03",
                "fee_usd": "0.006",
                "reason": "max_hold_exit",
            },
        ],
    )
    output = report.build_report(config, journal, tmp_path / "missing_path.csv")
    assert "Gross P/L: $0.0300" in output
    assert "Net P/L: $0.0180" in output
    assert "Max-hold exits: 1" in output


def test_missing_sell_fill_notional_is_not_reported_as_negative_100(tmp_path):
    config = tmp_path / "config.yaml"
    journal = tmp_path / "journal.csv"
    write_config(config)
    write_csv(
        journal,
        [
            {
                "timestamp": "2026-05-30T10:00:00Z",
                "symbol": "BTC/USD",
                "side": "buy",
                "quantity": "0.00001",
                "price": "100000",
                "notional": "1.00",
                "fee_usd": "0.006",
                "reason": "entry",
            },
            {
                "timestamp": "2026-05-30T11:30:00Z",
                "symbol": "BTC/USD",
                "side": "sell",
                "quantity": "",
                "price": "",
                "notional": "0.00",
                "fee_usd": "0.000",
                "reason": "max_hold_exit",
            },
        ],
    )
    output = report.build_report(config, journal, tmp_path / "missing_path.csv")
    assert "Exit notional: n/a" in output
    assert "Gross P/L: n/a" in output
    assert "Net P/L: n/a" in output
    assert "Gross return: n/a" in output
    assert "-100.000%" not in output
    assert "sell fill value unavailable" in output
    assert "Cycles with usable P/L: 0" in output


def test_zero_sell_can_reconstruct_from_quantity_and_price(tmp_path):
    config = tmp_path / "config.yaml"
    journal = tmp_path / "journal.csv"
    write_config(config)
    write_csv(
        journal,
        [
            {
                "timestamp": "2026-05-30T10:00:00Z",
                "symbol": "ETH/USD",
                "side": "buy",
                "quantity": "0.001",
                "price": "2000",
                "notional": "2.00",
                "reason": "entry",
            },
            {
                "timestamp": "2026-05-30T10:07:00Z",
                "symbol": "ETH/USD",
                "side": "sell",
                "quantity": "0.001",
                "price": "1990",
                "notional": "0.00",
                "reason": "stop-loss hit",
            },
        ],
    )
    output = report.build_report(config, journal, tmp_path / "missing_path.csv")
    assert "Exit notional: $1.9900" in output
    assert "SL exits: 1" in output


def test_threshold_crossing_merge_with_price_path(tmp_path):
    config = tmp_path / "config.yaml"
    journal = tmp_path / "journal.csv"
    price_path = tmp_path / "path.csv"
    write_config(config)
    write_csv(
        journal,
        [
            {
                "timestamp": "2026-05-30T10:00:00Z",
                "symbol": "SOL/USD",
                "side": "buy",
                "notional": "1.00",
            },
            {
                "timestamp": "2026-05-30T11:00:00Z",
                "symbol": "SOL/USD",
                "side": "sell",
                "notional": "1.02",
                "reason": "take_profit",
            },
        ],
    )
    write_csv(
        price_path,
        [
            {
                "timestamp": "2026-05-30T10:15:00Z",
                "symbol": "SOL/USD",
                "entry_timestamp": "2026-05-30T10:00:00Z",
                "unrealized_pct": "0.70",
                "hold_minutes": "15",
            },
            {
                "timestamp": "2026-05-30T10:35:00Z",
                "symbol": "SOL/USD",
                "entry_timestamp": "2026-05-30T10:00:00Z",
                "unrealized_pct": "1.30",
                "hold_minutes": "35",
            },
        ],
    )
    output = report.build_report(config, journal, price_path)
    assert "Price-path samples: 2" in output
    assert "MFE: +1.300%" in output
    assert "+1.20%=yes at 35.0m" in output


def test_dynamic_sizing_explanation_where_one_dollar_cap_wins(tmp_path):
    config = tmp_path / "config.yaml"
    journal = tmp_path / "journal.csv"
    write_config(config)
    write_csv(
        journal,
        [
            {"timestamp": "2026-05-30T10:00:00Z", "symbol": "SOL/USD", "side": "buy", "notional": "1.00"},
            {"timestamp": "2026-05-30T11:00:00Z", "symbol": "SOL/USD", "side": "sell", "notional": "1.01"},
        ],
    )
    output = report.build_report(config, journal, tmp_path / "missing_path.csv")
    assert "Dynamic theoretical: $1.0000" in output
    assert "Limiting factor: controlled_exploration.max_single_trade_notional_usd" in output


def test_symbol_summary_and_decision_gate(tmp_path):
    config = tmp_path / "config.yaml"
    journal = tmp_path / "journal.csv"
    write_config(config)
    write_csv(
        journal,
        [
            {"timestamp": "2026-05-30T10:00:00Z", "symbol": "BTC/USD", "side": "buy", "notional": "1.00"},
            {"timestamp": "2026-05-30T11:00:00Z", "symbol": "BTC/USD", "side": "sell", "notional": "0.99"},
        ],
    )
    output = report.build_report(config, journal, tmp_path / "missing_path.csv")
    assert "BTC/USD: cycles=1" in output
    assert "Class 2 tuning: BLOCKED" in output
    assert "Prediction/betting: SHADOW ONLY" in output


def test_forbidden_imports_not_present():
    source = MODULE_PATH.read_text(encoding="utf-8")
    forbidden = ["broker_", "order_manager", "risk_manager", "main.py", "dotenv", ".env"]
    for token in forbidden:
        assert token not in source
