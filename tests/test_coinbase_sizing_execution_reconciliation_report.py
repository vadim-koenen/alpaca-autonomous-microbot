# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""Tests for P2-006 Coinbase sizing / execution reconciliation report."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import coinbase_sizing_execution_reconciliation_report as report


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config_coinbase_crypto.yaml"
    path.write_text(
        """
crypto:
  max_trade_notional_usd: 2.00
  buying_power_safety_buffer: 0.85
  coinbase_probe_notional_usd: 0.50
  controlled_exploration:
    max_single_trade_notional_usd: 1.00
  dynamic_sizing:
    enabled: true
    min_notional_usd: 1.00
    max_notional_usd: 25.00
    scaling_threshold_usd: 20.00
    position_size_pct: 2.5
fees:
  maker_fee_pct: 0.006
  taker_fee_pct: 0.012
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _journal_row(**kwargs: str) -> dict[str, str]:
    base = {
        "timestamp": "2026-05-29T13:00:00Z",
        "symbol": "BTC/USD",
        "strategy": "coinbase_exploration",
        "action": "BUY",
        "decision": "PLACED",
        "notional": "1.0",
        "qty": "0.00001",
        "fill_price": "0",
        "exit_price": "0",
        "gross_pnl": "0",
        "fees_paid": "0",
        "pnl_usd": "0",
        "reason": "",
        "equity": "40.94",
        "buying_power": "40.0",
    }
    base.update(kwargs)
    return base


def test_load_sizing_config_from_yaml(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path)
    cfg = report.load_sizing_config(cfg_path)
    assert cfg.config_found is True
    assert cfg.probe_notional_usd == 0.50
    assert cfg.max_single_trade_notional_usd == 1.00
    assert cfg.dynamic_enabled is True


def test_compute_dynamic_clamped_to_hard_cap(tmp_path: Path) -> None:
    cfg = report.load_sizing_config(_write_config(tmp_path))
    # equity 40 < threshold 20? threshold is 20, 40 > 20 so 40*2.5% = 1.0
    dynamic = report.compute_dynamic_notional(40.94, 40.0, cfg)
    assert dynamic == 1.00


def test_extract_cycle_pairing(tmp_path: Path) -> None:
    cfg = report.SizingConfig(
        probe_notional_usd=0.50,
        max_single_trade_notional_usd=1.00,
        dynamic_enabled=True,
    )
    rows = [
        _journal_row(
            timestamp="2026-05-29T13:00:00Z",
            action="BUY",
            decision="PLACED",
            notional="1.0",
        ),
        _journal_row(
            timestamp="2026-05-29T14:30:00Z",
            action="EXIT",
            decision="PLACED",
            notional="0",
            fill_price="100.0",
            exit_price="100.5",
            qty="0.01",
            gross_pnl="0.005",
            fees_paid="0.012",
            pnl_usd="-0.007",
            reason="max hold time 90min exceeded",
        ),
    ]
    cycles = report.extract_cycles(rows, cfg)
    assert len(cycles) == 1
    c = cycles[0]
    assert c.journal_proposed_notional == 1.0
    assert c.filled_buy_notional == 1.0
    assert c.filled_sell_notional == pytest.approx(1.005)
    assert c.net_pnl == pytest.approx(-0.007)
    assert "hard cap" in c.winning_cap or "1.00" in c.winning_cap or "journal" in c.winning_cap


def test_missing_journal_handled(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path)
    out = report.run_analysis(cfg_path, journal_path=tmp_path / "missing.csv")
    assert "Journal: not found" in out or "No completed exploration" in out
    assert "fixed-cap controlled exploration" in out


def test_summary_messages_present(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path)
    journal = tmp_path / "journal.csv"
    with open(journal, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(_journal_row().keys()))
        writer.writeheader()
        writer.writerow(_journal_row(timestamp="2026-05-29T13:00:00Z", action="BUY", decision="PLACED"))
        writer.writerow(
            _journal_row(
                timestamp="2026-05-29T14:00:00Z",
                action="EXIT",
                decision="PLACED",
                fill_price="100",
                exit_price="100.2",
                qty="0.01",
                gross_pnl="0.002",
                fees_paid="0.012",
                pnl_usd="-0.01",
                reason="max hold",
            )
        )
    out = report.run_analysis(cfg_path, journal)
    assert "fixed-cap controlled exploration" in out
    assert "Sells close the same position quantity" in out
    assert "Class 2" in out and "BLOCKED" in out


def test_probe_notional_path_detection(tmp_path: Path) -> None:
    cfg = report.SizingConfig(probe_notional_usd=0.50, max_single_trade_notional_usd=1.00)
    cap, final = report.determine_winning_cap(0.50, None, cfg, "coinbase_probe")
    assert final == 0.50
    assert "0.50" in cap


def test_price_path_mfe_attachment(tmp_path: Path) -> None:
    path_csv = tmp_path / "coinbase_price_path.csv"
    with open(path_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp_utc",
                "symbol",
                "position_id",
                "entry_price",
                "current_price",
                "unrealized_pct",
                "hold_minutes",
                "entry_timestamp",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "timestamp_utc": "2026-05-29T14:00:00Z",
                "symbol": "BTC/USD",
                "position_id": "p1",
                "entry_price": "100",
                "current_price": "100.8",
                "unrealized_pct": "0.8",
                "hold_minutes": "30",
                "entry_timestamp": "2026-05-29T13:00:00Z",
            }
        )
    mfe_index = {}
    with open(path_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            symbol = row["symbol"]
            entry_ts = row["entry_timestamp"]
            u = float(row["unrealized_pct"])
            key = (symbol, entry_ts)
            prev, count = mfe_index.get(key, (u, 0))
            mfe_index[key] = (max(prev, u), count + 1)
    cycles = [
        report.TradeCycle(
            symbol="BTC/USD",
            strategy="coinbase_exploration",
            entry_timestamp="2026-05-29T13:00:00Z",
            exit_timestamp="2026-05-29T14:00:00Z",
            configured_probe_notional=0.5,
            exploration_hard_cap=1.0,
            dynamic_calculated_notional=1.0,
            journal_proposed_notional=1.0,
            winning_cap="cap",
            final_applied_notional=1.0,
            filled_buy_notional=1.0,
            filled_sell_notional=1.0,
            qty=0.01,
            entry_price=100.0,
            exit_price=100.2,
            gross_pnl=0.002,
            total_fees=0.012,
            net_pnl=-0.01,
            exit_reason="max hold",
            hold_minutes=60.0,
        )
    ]
    report.attach_mfe(cycles, mfe_index)
    assert cycles[0].mfe_pct == 0.8
    assert cycles[0].beat_maker_be is True
    assert cycles[0].beat_taker_be is False


def test_no_forbidden_imports() -> None:
    text = Path(report.__file__).read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            lower = stripped.lower()
            for mod in ("broker", "order_manager", "risk_manager", "main"):
                assert mod not in lower, stripped
