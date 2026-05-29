"""
journal.py — Append-only CSV trade journal.

Logs EVERY decision: placed trades, skipped trades, exits, errors.
A bot that only logs fills is unacceptable — this logs non-trades too.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from utils import ROOT, load_config, safe_float, utc_ts

logger = logging.getLogger("journal")

# ---------------------------------------------------------------------------
# Journal row schema
# ---------------------------------------------------------------------------

@dataclass
class JournalRow:
    timestamp: str = ""
    mode: str = ""
    asset_class: str = ""
    symbol: str = ""
    strategy: str = ""
    action: str = ""           # BUY | SELL | SHORT | COVER | SKIP | EXIT | ERROR
    decision: str = ""         # PLACED | SKIPPED | FILLED | PARTIAL | REJECTED
    reason: str = ""
    confidence: float = 0.0
    price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    spread_pct: float = 0.0
    notional: float = 0.0
    qty: float = 0.0
    order_type: str = ""
    order_id: str = ""
    client_order_id: str = ""
    intent_key: str = ""
    status: str = ""
    fill_price: float = 0.0
    exit_price: float = 0.0
    gross_pnl: float = 0.0    # P/L before fees
    fees_paid: float = 0.0    # estimated round-trip fees in USD
    pnl_usd: float = 0.0      # net P/L after fees (authoritative figure)
    pnl_pct: float = 0.0      # net P/L % after fees
    equity: float = 0.0
    buying_power: float = 0.0
    open_positions: int = 0
    daily_trade_count: int = 0
    consecutive_losses: int = 0
    error: str = ""

    @classmethod
    def columns(cls) -> list[str]:
        return [f.name for f in fields(cls)]


# ---------------------------------------------------------------------------
# Journal writer
# ---------------------------------------------------------------------------

class Journal:
    def __init__(self) -> None:
        cfg = load_config()
        log_cfg = cfg.get("logging", {})
        journal_file = log_cfg.get("journal_file", "journal.csv")
        self._path = ROOT / journal_file
        self._log_skipped = log_cfg.get("log_skipped_trades", True)
        self._ensure_header()

    def _ensure_header(self) -> None:
        if not self._path.exists():
            with open(self._path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(JournalRow.columns())
            return

        try:
            with open(self._path, "r", newline="") as f:
                reader = csv.DictReader(f)
                existing_columns = reader.fieldnames or []
                if existing_columns == JournalRow.columns():
                    return
                rows = list(reader)

            tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
            with open(tmp_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=JournalRow.columns())
                writer.writeheader()
                for row in rows:
                    writer.writerow({col: row.get(col, "") for col in JournalRow.columns()})
            tmp_path.replace(self._path)
            logger.info(
                f"Journal schema migrated at {self._path.name}: "
                f"{len(existing_columns)} → {len(JournalRow.columns())} columns"
            )
        except Exception as e:
            logger.error(f"JOURNAL HEADER CHECK ERROR: {e}")

    def log(self, row: JournalRow) -> None:
        """Append one row to journal.csv."""
        if not row.timestamp:
            row.timestamp = utc_ts()
        try:
            with open(self._path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([getattr(row, c) for c in JournalRow.columns()])
        except Exception as e:
            logger.error(f"JOURNAL WRITE ERROR: {e}")

    def log_skip(
        self,
        *,
        symbol: str,
        asset_class: str,
        strategy: str,
        reason: str,
        action: str = "SKIP",
        confidence: float = 0.0,
        price: float = 0.0,
        bid: float = 0.0,
        ask: float = 0.0,
        spread_pct: float = 0.0,
        notional: float = 0.0,
        equity: float = 0.0,
        buying_power: float = 0.0,
        open_positions: int = 0,
        daily_trade_count: int = 0,
        consecutive_losses: int = 0,
        mode: str = "",
        intent_key: str = "",
    ) -> None:
        if not self._log_skipped:
            return
        row = JournalRow(
            timestamp=utc_ts(),
            mode=mode,
            asset_class=asset_class,
            symbol=symbol,
            strategy=strategy,
            action=action,
            decision="SKIPPED",
            reason=reason,
            confidence=confidence,
            price=price,
            bid=bid,
            ask=ask,
            spread_pct=spread_pct,
            notional=notional,
            equity=equity,
            buying_power=buying_power,
            open_positions=open_positions,
            daily_trade_count=daily_trade_count,
            consecutive_losses=consecutive_losses,
            intent_key=intent_key,
        )
        self.log(row)
        logger.info(
            f"SKIP | {symbol} | {strategy} | {reason}"
        )

    def log_order(
        self,
        *,
        symbol: str,
        asset_class: str,
        strategy: str,
        action: str,
        order_id: str,
        status: str,
        qty: float,
        notional: float,
        price: float,
        order_type: str,
        client_order_id: str = "",
        intent_key: str = "",
        decision: str = "PLACED",
        reason: str = "",
        bid: float = 0.0,
        ask: float = 0.0,
        spread_pct: float = 0.0,
        confidence: float = 0.0,
        equity: float = 0.0,
        buying_power: float = 0.0,
        open_positions: int = 0,
        daily_trade_count: int = 0,
        consecutive_losses: int = 0,
        mode: str = "",
        error: str = "",
    ) -> None:
        row = JournalRow(
            timestamp=utc_ts(),
            mode=mode,
            asset_class=asset_class,
            symbol=symbol,
            strategy=strategy,
            action=action,
            decision=decision,
            reason=reason,
            order_id=order_id,
            client_order_id=client_order_id,
            intent_key=intent_key,
            status=status,
            qty=qty,
            notional=notional,
            price=price,
            order_type=order_type,
            bid=bid,
            ask=ask,
            spread_pct=spread_pct,
            confidence=confidence,
            equity=equity,
            buying_power=buying_power,
            open_positions=open_positions,
            daily_trade_count=daily_trade_count,
            consecutive_losses=consecutive_losses,
            error=error,
        )
        self.log(row)
        logger.info(
            f"ORDER | {action} | {symbol} | qty={qty} notional={notional} | "
            f"{status} | client_order_id={client_order_id}"
        )

    def log_order_preview(
        self,
        *,
        symbol: str,
        asset_class: str,
        strategy: str,
        action: str,
        client_order_id: str,
        intent_key: str,
        qty: float,
        notional: float,
        price: float,
        order_type: str,
        bid: float = 0.0,
        ask: float = 0.0,
        spread_pct: float = 0.0,
        confidence: float = 0.0,
        equity: float = 0.0,
        buying_power: float = 0.0,
        open_positions: int = 0,
        daily_trade_count: int = 0,
        consecutive_losses: int = 0,
        mode: str = "",
    ) -> None:
        self.log_order(
            symbol=symbol,
            asset_class=asset_class,
            strategy=strategy,
            action=action,
            order_id="",
            client_order_id=client_order_id,
            intent_key=intent_key,
            status="preview",
            decision="PREVIEW",
            qty=qty,
            notional=notional,
            price=price,
            order_type=order_type,
            bid=bid,
            ask=ask,
            spread_pct=spread_pct,
            confidence=confidence,
            equity=equity,
            buying_power=buying_power,
            open_positions=open_positions,
            daily_trade_count=daily_trade_count,
            consecutive_losses=consecutive_losses,
            mode=mode,
        )

    def find_recent_order_intent(
        self,
        intent_key: str,
        *,
        window_seconds: int,
    ) -> dict[str, str] | None:
        """Return the newest recent journal row for this intent key, if any."""
        if not intent_key or not self._path.exists():
            return None
        cutoff = datetime.now(timezone.utc).timestamp() - max(0, window_seconds)
        newest: dict[str, str] | None = None
        newest_ts = 0.0
        try:
            with open(self._path, "r", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("intent_key", "") != intent_key:
                        continue
                    if row.get("decision", "") not in {"PREVIEW", "PLACED", "BLOCKED"}:
                        continue
                    raw_ts = row.get("timestamp", "")
                    try:
                        parsed = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        ts = parsed.timestamp()
                    except Exception:
                        continue
                    if ts >= cutoff and ts >= newest_ts:
                        newest = dict(row)
                        newest_ts = ts
            return newest
        except Exception as e:
            logger.warning(f"Journal recent intent scan failed: {e}")
            return {
                "intent_key": intent_key,
                "error": str(e),
                "source": "journal_recent_error",
            }

    def find_recent_bot_entry(
        self,
        symbol: str,
        *,
        qty: float = 0.0,
        notional: float = 0.0,
        window_seconds: int = 24 * 60 * 60,
    ) -> dict[str, str] | None:
        """
        Return the newest recent bot BUY row with matching local provenance.

        This is used only to re-associate a broker-visible balance with a
        previously journaled bot order. It requires order/client ids and either
        a quantity match or, if quantity is unavailable, a notional match. A
        later close/error row for the same symbol invalidates older candidates.
        """
        if not symbol or not self._path.exists():
            return None

        def parse_ts(raw_ts: str) -> float | None:
            try:
                parsed = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except Exception:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()

        def close_enough(expected: float, actual: float, *, pct: float = 0.02) -> bool:
            if expected <= 0 or actual <= 0:
                return False
            tolerance = max(abs(expected) * pct, 1e-12)
            return abs(expected - actual) <= tolerance

        cutoff = datetime.now(timezone.utc).timestamp() - max(0, window_seconds)
        candidates: list[tuple[float, dict[str, str]]] = []
        close_times: list[float] = []

        try:
            with open(self._path, "r", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("symbol", "") != symbol:
                        continue

                    ts = parse_ts(row.get("timestamp", ""))
                    if ts is None:
                        continue

                    action = row.get("action", "").upper()
                    error = row.get("error", "")
                    if action in {"EXIT", "SELL"} or "Position closed" in error:
                        close_times.append(ts)

                    if ts < cutoff:
                        continue
                    if action != "BUY":
                        continue
                    if row.get("decision", "").upper() not in {"PLACED", "FILLED"}:
                        continue
                    if row.get("strategy", "") in {"", "recovered"}:
                        continue
                    if not (row.get("order_id", "") or row.get("client_order_id", "")):
                        continue

                    row_qty = safe_float(row.get("qty", 0))
                    row_notional = safe_float(row.get("notional", 0))
                    if qty > 0:
                        if not close_enough(qty, row_qty):
                            continue
                    elif notional > 0 and not close_enough(notional, row_notional):
                        continue

                    candidates.append((ts, dict(row)))

            for ts, row in sorted(candidates, key=lambda item: item[0], reverse=True):
                if any(close_ts > ts for close_ts in close_times):
                    continue
                row["source"] = "journal_recent_bot_entry"
                return row
            return None
        except Exception as e:
            logger.warning(f"Journal recent bot-entry scan failed: {e}")
            return {
                "symbol": symbol,
                "error": str(e),
                "source": "journal_recent_error",
            }

    def log_exit(
        self,
        *,
        symbol: str,
        asset_class: str,
        strategy: str,
        exit_price: float,
        entry_price: float,
        qty: float,
        gross_pnl: float,
        fees_paid: float,
        pnl_usd: float,
        pnl_pct: float,
        reason: str,
        order_id: str = "",
        client_order_id: str = "",
        intent_key: str = "",
        mode: str = "",
    ) -> None:
        row = JournalRow(
            timestamp=utc_ts(),
            mode=mode,
            asset_class=asset_class,
            symbol=symbol,
            strategy=strategy,
            action="EXIT",
            decision="PLACED",
            reason=reason,
            exit_price=exit_price,
            fill_price=entry_price,
            qty=qty,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            order_id=order_id,
            client_order_id=client_order_id,
            intent_key=intent_key,
        )
        self.log(row)
        pnl_sign = "+" if pnl_usd >= 0 else ""
        logger.info(
            f"EXIT | {symbol} | {reason} | "
            f"gross={'+' if gross_pnl >= 0 else ''}{gross_pnl:.4f} "
            f"fees=-{fees_paid:.4f} "
            f"net={pnl_sign}{pnl_usd:.4f} ({pnl_sign}{pnl_pct:.2f}%)"
        )

    def log_warning(self, *, symbol: str, warning: str, mode: str = "") -> None:
        row = JournalRow(
            timestamp=utc_ts(),
            mode=mode,
            symbol=symbol,
            action="WARN",
            decision="WARN",
            error=warning,
        )
        self.log(row)
        logger.warning(f"WARN | {symbol} | {warning}")

    def log_error(self, *, symbol: str, error: str, mode: str = "") -> None:
        row = JournalRow(
            timestamp=utc_ts(),
            mode=mode,
            symbol=symbol,
            action="ERROR",
            decision="ERROR",
            error=error,
        )
        self.log(row)
        logger.error(f"ERROR | {symbol} | {error}")


# Singleton for use across modules
_journal: Journal | None = None


def get_journal() -> Journal:
    global _journal
    if _journal is None:
        _journal = Journal()
    return _journal
