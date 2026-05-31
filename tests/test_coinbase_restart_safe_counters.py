"""
P2-011K tests for restart-safe daily counter reconstruction from journal.

Uses a temporary journal file with controlled rows for the "today" date.
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from runtime_safety import reconstruct_daily_counters_from_journal


def _write_journal(path: Path, rows: list[str]):
    header = "timestamp,mode,asset_class,symbol,strategy,action,decision,reason,confidence,price,bid,ask,spread_pct,notional,qty,order_type,order_id,client_order_id,intent_key,status,fill_price,exit_price,gross_pnl,fees_paid,pnl_usd,pnl_pct,equity,buying_power,open_positions,daily_trade_count,consecutive_losses,error\n"
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def test_reconstructs_daily_trade_count_and_pnl_same_day():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    journal = Path(tempfile.mktemp(suffix=".csv"))

    rows = [
        f"{today}T10:00:00Z,live,crypto,BTC/USD,,BUY,PLACED,reason,0.0,65000,65000,65000,0.0,65.0,0.001,,,,,,0,0,0,0,0.0,0.0,0,0,0,0,0,0,",
        f"{today}T11:30:00Z,live,crypto,ETH/USD,,SELL,PLACED,reason,0.0,65100,65100,65100,0.0,130.2,0.002,,,,,,0,0,0,0,0.0,0.0,0,0,0,0,0,0,",
        f"{today}T12:05:00Z,live,crypto,BTC/USD,,EXIT,PLACED,max hold,0.0,65000,65000,65000,0.0,65.0,0.001,,,,,,0.5,0.002,0.3,0.001,0.299,0.46,0,0,0,0,0,0,",
    ]
    _write_journal(journal, rows)

    recon = reconstruct_daily_counters_from_journal(journal, today=today)

    assert recon["daily_trade_count"] >= 2  # at least the two PLACED rows
    assert recon["_last_daily_reset_date"] == today
    # daily_realized_pnl should include the realized exit
    assert recon["daily_realized_pnl"] > 0

    journal.unlink(missing_ok=True)


def test_does_not_count_rows_from_previous_day():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc).replace(day=datetime.now(timezone.utc).day - 1)).strftime("%Y-%m-%d")

    journal = Path(tempfile.mktemp(suffix=".csv"))
    rows = [
        f"{yesterday}T23:50:00Z,live,crypto,BTC/USD,,BUY,PLACED,reason,0.0,65000,65000,65000,0.0,65.0,0.001,,,,,,0,0,0,0,0.0,0.0,0,0,0,0,0,0,",
        f"{today}T00:10:00Z,live,crypto,ETH/USD,,SELL,PLACED,reason,0.0,65100,65100,65100,0.0,130.2,0.002,,,,,,0,0,0,0,0.0,0.0,0,0,0,0,0,0,",
    ]
    _write_journal(journal, rows)

    recon = reconstruct_daily_counters_from_journal(journal, today=today)
    # Only the today row should count
    assert recon["daily_trade_count"] == 1

    journal.unlink(missing_ok=True)


def test_no_double_counting_of_preview_or_warn_rows():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    journal = Path(tempfile.mktemp(suffix=".csv"))

    rows = [
        f"{today}T09:00:00Z,live,crypto,BTC/USD,,BUY,PREVIEW,reason,0.0,65000,65000,65000,0.0,65.0,0.001,,,,,,0,0,0,0,0.0,0.0,0,0,0,0,0,0,",
        f"{today}T09:01:00Z,live,crypto,BTC/USD,,BUY,PLACED,reason,0.0,65000,65000,65000,0.0,65.0,0.001,,,,,,0,0,0,0,0.0,0.0,0,0,0,0,0,0,",
        f"{today}T09:05:00Z,live,crypto,BTC/USD,,WARN,WARN,Fill confirmation,0.0,0,0,0,0,0,0,,,,,,0,0,0,0,0.0,0.0,0,0,0,0,0,0,",
    ]
    _write_journal(journal, rows)

    recon = reconstruct_daily_counters_from_journal(journal, today=today)
    # Only the real PLACED row should count as a trade for the day
    assert recon["daily_trade_count"] == 1

    journal.unlink(missing_ok=True)
