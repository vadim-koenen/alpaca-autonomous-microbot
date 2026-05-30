# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""Tests for P2-005 Coinbase price-path MFE/MAE analyzer."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import coinbase_price_path_mfe_mae_report as report


def _write_csv(path: Path, rows: list[dict[str, str]], write_header: bool = True) -> None:
    fieldnames = list(report.FIELDNAMES)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def _sample_row(
    ts: str,
    symbol: str,
    position_id: str,
    entry_ts: str,
    unrealized: float,
    hold: float,
    entry_price: float = 100.0,
    current_price: float | None = None,
) -> dict[str, str]:
    if current_price is None:
        current_price = entry_price * (1 + unrealized / 100.0)
    return {
        "timestamp_utc": ts,
        "symbol": symbol,
        "position_id": position_id,
        "entry_price": str(entry_price),
        "current_price": str(current_price),
        "unrealized_pct": str(unrealized),
        "hold_minutes": str(hold),
        "entry_timestamp": entry_ts,
    }


def test_missing_csv_handling(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    rows, err = report.read_price_path_csv(missing)
    assert rows == []
    assert err is not None
    out = report.run_analysis(missing)
    assert "CSV not found" in out
    assert "No position analysis" in out


def test_empty_csv_handling(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("timestamp_utc,symbol,position_id,entry_price,current_price,unrealized_pct,hold_minutes,entry_timestamp\n")
    rows, err = report.read_price_path_csv(path)
    assert err is None
    assert rows == []
    out = report.run_analysis(path)
    assert "no data rows" in out.lower()


def test_grouping_by_position_key(tmp_path: Path) -> None:
    path = tmp_path / "grouped.csv"
    entry = "2026-05-30T13:00:00+00:00"
    _write_csv(
        path,
        [
            _sample_row("2026-05-30T14:00:00Z", "BTC/USD", "p1", entry, 0.5, 10.0),
            _sample_row("2026-05-30T14:01:00Z", "BTC/USD", "p1", entry, 1.0, 11.0),
            _sample_row("2026-05-30T14:00:00Z", "ETH/USD", "p2", "2026-05-30T12:00:00+00:00", -0.2, 5.0),
        ],
    )
    rows, _ = report.read_price_path_csv(path)
    grouped = report.group_rows_by_position(rows)
    assert len(grouped) == 2
    btc_key = report.PositionKey("p1", "BTC/USD", entry)
    assert btc_key in grouped
    assert len(grouped[btc_key]) == 2


def test_mfe_mae_calculation(tmp_path: Path) -> None:
    entry = "2026-05-30T13:00:00+00:00"
    samples = [
        _sample_row("2026-05-30T14:00:00Z", "BTC/USD", "p1", entry, 0.5, 10.0),
        _sample_row("2026-05-30T14:05:00Z", "BTC/USD", "p1", entry, 1.8, 15.0),
        _sample_row("2026-05-30T14:10:00Z", "BTC/USD", "p1", entry, -0.3, 20.0),
    ]
    key = report.PositionKey("p1", "BTC/USD", entry)
    analysis = report.analyze_position(key, samples)
    assert analysis.sample_count == 3
    assert analysis.mfe_pct == 1.8
    assert analysis.mae_pct == -0.3
    assert analysis.latest_unrealized_pct == -0.3
    assert analysis.max_hold_minutes == 20.0


def test_threshold_crossing_detection() -> None:
    entry = "2026-05-30T13:00:00+00:00"
    samples = [
        _sample_row("2026-05-30T14:00:00Z", "BTC/USD", "p1", entry, 0.5, 10.0),
        _sample_row("2026-05-30T14:05:00Z", "BTC/USD", "p1", entry, 1.25, 15.0),
        _sample_row("2026-05-30T14:10:00Z", "BTC/USD", "p1", entry, 2.5, 20.0),
    ]
    crossings = report.detect_threshold_crossings(samples)
    by_thr = {c.threshold_pct: c for c in crossings}
    assert by_thr[0.60].crossed is True
    assert by_thr[1.20].crossed is True
    assert by_thr[1.20].first_timestamp_utc == "2026-05-30T14:05:00Z"
    assert by_thr[1.20].first_hold_minutes == 15.0
    assert by_thr[2.40].crossed is True
    assert by_thr[2.40].first_timestamp_utc == "2026-05-30T14:10:00Z"


def test_fallback_below_120_after_crossing_120() -> None:
    entry = "2026-05-30T13:00:00+00:00"
    samples = [
        _sample_row("2026-05-30T14:00:00Z", "BTC/USD", "p1", entry, 1.5, 10.0),
        _sample_row("2026-05-30T14:05:00Z", "BTC/USD", "p1", entry, 0.8, 15.0),
    ]
    key = report.PositionKey("p1", "BTC/USD", entry)
    analysis = report.analyze_position(key, samples)
    assert analysis.fallback_below_120_after_cross_120 is True


def test_fallback_after_150_cross() -> None:
    entry = "2026-05-30T13:00:00+00:00"
    samples = [
        _sample_row("2026-05-30T14:00:00Z", "BTC/USD", "p1", entry, 1.6, 10.0),
        _sample_row("2026-05-30T14:05:00Z", "BTC/USD", "p1", entry, 1.0, 15.0),
    ]
    key = report.PositionKey("p1", "BTC/USD", entry)
    analysis = report.analyze_position(key, samples)
    assert analysis.fallback_below_120_after_cross_150 is True


def test_by_symbol_summary() -> None:
    entry_btc = "2026-05-30T13:00:00+00:00"
    entry_eth = "2026-05-30T12:00:00+00:00"
    positions = [
        report.analyze_position(
            report.PositionKey("b1", "BTC/USD", entry_btc),
            [
                _sample_row("2026-05-30T14:00:00Z", "BTC/USD", "b1", entry_btc, 1.3, 10.0),
                _sample_row("2026-05-30T14:05:00Z", "BTC/USD", "b1", entry_btc, 2.5, 15.0),
            ],
        ),
        report.analyze_position(
            report.PositionKey("e1", "ETH/USD", entry_eth),
            [_sample_row("2026-05-30T14:00:00Z", "ETH/USD", "e1", entry_eth, 0.4, 5.0)],
        ),
    ]
    summaries = report.build_symbol_summaries(positions)
    btc = next(s for s in summaries if s.symbol == "BTC/USD")
    eth = next(s for s in summaries if s.symbol == "ETH/USD")
    assert btc.positions_observed == 1
    assert btc.total_samples == 2
    assert btc.max_mfe_pct == 2.5
    assert btc.pct_crossed_120 == 100.0
    assert btc.pct_crossed_240 == 100.0
    assert eth.pct_crossed_120 == 0.0


def test_conservative_not_enough_data_verdict() -> None:
    entry = "2026-05-30T13:00:00+00:00"
    positions = [
        report.analyze_position(
            report.PositionKey(f"p{i}", "BTC/USD", f"{entry}-{i}"),
            [_sample_row("2026-05-30T14:00:00Z", "BTC/USD", f"p{i}", f"{entry}-{i}", 0.5, 10.0)],
        )
        for i in range(5)
    ]
    verdict = report.build_advisory_verdict(positions, span_days=3.0)
    text = "\n".join(verdict)
    assert "too small" in text.lower() or "fewer than 20" in text.lower()
    assert "premature" in text.lower() or "BLOCKED" in text
    assert "Class 2" in text


def test_no_forbidden_imports() -> None:
    source_path = Path(report.__file__)
    text = source_path.read_text(encoding="utf-8")
    forbidden = ("broker", "order_manager", "risk_manager", "main")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            lower = stripped.lower()
            for mod in forbidden:
                assert mod not in lower, f"Forbidden import line: {stripped}"


def test_full_report_stdout(tmp_path: Path) -> None:
    path = tmp_path / "path.csv"
    entry = "2026-05-30T13:00:00+00:00"
    _write_csv(
        path,
        [
            _sample_row("2026-05-30T14:00:00Z", "BTC/USD", "p1", entry, 0.7, 60.0),
            _sample_row("2026-05-30T14:30:00Z", "BTC/USD", "p1", entry, 1.3, 90.0),
        ],
    )
    out = report.run_analysis(path)
    assert "MFE" in out
    assert "BTC/USD" in out
    assert "ADVISORY VERDICT" in out
