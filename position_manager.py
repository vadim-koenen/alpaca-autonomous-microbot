"""
position_manager.py — Open position monitor and exit manager.

Polls all open positions and applies:
  1. Stop-loss: force-close when price crosses stop level
  2. Take-profit: close when price hits target
  3. Max hold time: close position after N minutes regardless of P/L
  4. Force-flat: close all non-crypto positions before market close
  5. Abandoned-position detection: if a position exists with no tracked
     session entry, log a warning and optionally close it

Exit orders are routed through broker.close_position(), which respects
dry_run mode (no-op if dry_run).

The position manager also feeds realized P/L back to SessionState so
the risk manager's daily-loss check stays accurate.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from broker_alpaca import BrokerAlpaca
from journal import Journal
from memory.event_store import get_event_store
from order_manager import SessionState
from utils import get_cfg, get_mode, load_saved_positions, now_utc, now_local, safe_float, save_positions

logger = logging.getLogger("position_manager")

# Order statuses that are terminal — no further broker polling is needed.
# Any status NOT in this set (including missing/None) triggers a reconcile
# poll if the position also carries a non-empty order_id.
_TERMINAL_ORDER_STATUSES = frozenset({
    "filled",
    "canceled",
    "rejected",
    "expired",
    "dry_run_simulated",
    # Broker-recovered positions have no order_id — they are confirmed at
    # the broker but were not placed by this bot session.  Treat as terminal
    # so reconciliation polling is never attempted.
    "broker_recovered",
})

_BOT_POSITION_VISIBILITY_GRACE_MINUTES = 10
_JOURNAL_REASSOCIATION_WINDOW_SECONDS = 24 * 60 * 60
COINBASE_EXTERNAL_INVENTORY_PATH = Path("state") / "coinbase" / "external_inventory.json"


def _normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper().replace("-", "/")


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "y"):
            return True
        if text in ("false", "0", "no", "n"):
            return False
    return None


def _external_inventory_records(path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    path = path or COINBASE_EXTERNAL_INVENTORY_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data, dict) and isinstance(data.get("external_inventory"), dict):
        data = data["external_inventory"]
    if not isinstance(data, dict):
        return {}
    return {str(sym): dict(record) for sym, record in data.items() if isinstance(record, dict)}


def _is_authoritative_external_inventory(record: dict[str, Any]) -> bool:
    classification = str(record.get("external_inventory_classification") or "").lower()
    return (
        "external" in classification
        and "staked" in classification
        and _as_bool(record.get("staked_external_position")) is True
        and _as_bool(record.get("bot_inventory")) is False
        and _as_bool(record.get("tradable_by_bot")) is False
        and _as_bool(record.get("manual_close_allowed")) is False
        and record.get("blocks_new_entries", False) is False
    )


def _external_inventory_record_for_symbol(symbol: str, path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    path = path or COINBASE_EXTERNAL_INVENTORY_PATH
    normalized = _normalize_symbol(symbol)
    for raw_symbol, record in _external_inventory_records(path).items():
        record_symbol = _normalize_symbol(record.get("symbol") or raw_symbol)
        if record_symbol == normalized and _is_authoritative_external_inventory(record):
            return record
    return None


def _write_external_inventory_observation(
    symbol: str,
    *,
    qty: float,
    observed_notional: float,
    path: Optional[Path] = None,
) -> None:
    path = path or COINBASE_EXTERNAL_INVENTORY_PATH
    record = _external_inventory_record_for_symbol(symbol, path)
    if record is None:
        return
    records = _external_inventory_records(path)
    target_key = next(
        (
            raw_symbol
            for raw_symbol, existing in records.items()
            if _normalize_symbol(existing.get("symbol") or raw_symbol) == _normalize_symbol(symbol)
        ),
        symbol,
    )
    updated = dict(record)
    updated.update({
        "symbol": _normalize_symbol(symbol),
        "last_seen_on_broker": True,
        "last_seen_at": now_utc().isoformat(),
        "observed_qty": qty,
        "observed_notional": observed_notional,
        "no_pnl_inference": True,
        "no_close_attempted": True,
        "blocks_new_entries": False,
    })
    records[target_key] = updated
    payload = {
        "updated_at": now_utc().isoformat(),
        "external_inventory": records,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning(f"external_inventory_update_failed symbol={symbol}: {exc}")


class PositionManager:
    def __init__(self, broker: BrokerAlpaca, journal: Journal, *, dry_run_capture: bool = False) -> None:
        """
        ADVISORY / P2-011H OPT-IN DRY-RUN ONLY

        dry_run_capture: When True, the manager will attempt inert entry/exit
        capture using order status + historical fills via the P2-011G helpers.
        This is completely disabled by default (False) and has no effect on
        trading decisions, P/L recording, or any live behavior.
        """
        self._broker = broker
        self._journal = journal
        self._mode = get_mode()
        self._dry_run_capture = dry_run_capture
        self._dry_run_captures: list = []  # populated only when dry_run_capture=True; for test inspection only
        self._mfe_mae_params_cache = None

    def restore_state(self, session: SessionState) -> None:
        """
        Load previously saved open_positions from disk and merge into session.

        Only restores positions that are still open at the broker — stale
        entries (positions closed while the bot was offline) are discarded.
        This runs once at startup, before the first monitor() call.
        """
        saved = load_saved_positions()
        if not saved:
            return

        try:
            broker_positions = self._broker.get_all_positions()
            broker_syms = {getattr(p, "symbol", "") for p in broker_positions}
        except Exception as e:
            logger.error(f"restore_state: failed to fetch broker positions: {e}")
            return

        restored = 0
        for sym, pos_data in saved.items():
            if _external_inventory_record_for_symbol(sym):
                logger.info(
                    f"restore_state: {sym} is authoritative external/staked inventory; "
                    "not restoring into active open_positions"
                )
                continue
            if sym not in broker_syms:
                if self._should_keep_without_broker_position(sym, pos_data):
                    logger.warning(
                        f"restore_state: {sym} in saved state but NOT at broker — "
                        "keeping for order/status reconciliation/manual review"
                    )
                else:
                    logger.info(
                        f"restore_state: {sym} in saved state but NOT at broker — discarding"
                    )
                    continue
            if sym in session.open_positions:
                logger.debug(f"restore_state: {sym} already in session — keeping live version")
                continue
            session.open_positions[sym] = pos_data
            restored += 1
            logger.info(
                f"restore_state: restored {sym} "
                f"(entry={pos_data.get('entry_price', '?')} "
                f"stop={pos_data.get('stop_loss', '?')} "
                f"tp={pos_data.get('take_profit', '?')})"
            )

        if restored:
            logger.info(f"restore_state: {restored} position(s) restored from disk")
            # Backfill order_status for any positions that were saved before
            # the reconciliation patch (they have an order_id but no
            # order_status, which load_saved_positions() marks "pending_new").
            # This runs once at startup — ongoing polling is handled by
            # _reconcile_pending_orders() in each monitor() call.
            self._backfill_missing_order_status(session)
            save_positions(session.open_positions)  # re-save with all fields normalised

    def _remove_stale_session_positions(
        self,
        session: SessionState,
        broker_symbols: set[str],
    ) -> None:
        """Drop session entries absent at broker, except orders still reconciling."""
        changed = False
        for sym in list(session.open_positions):
            if sym in broker_symbols:
                continue
            tracked = session.open_positions.get(sym, {})
            if self._should_keep_without_broker_position(sym, tracked):
                logger.debug(
                    f"{sym}: absent from broker position snapshot but retained "
                    "for order/status reconciliation/manual review"
                )
                continue
            logger.info(f"Position {sym} no longer at broker — removing from session")
            del session.open_positions[sym]
            changed = True
        if changed:
            save_positions(session.open_positions)

    def _should_keep_without_broker_position(self, symbol: str, position: dict) -> bool:
        """
        Keep manual-review and bot-created entries through Coinbase visibility lag.

        Coinbase wallet/portfolio visibility can flicker. A broker_recovered
        position is deliberately manual-review state, so a single missing
        broker snapshot should not drop it and let the next visible snapshot
        re-adopt it again. Separately, a real order_id with a non-terminal
        status must survive long enough for get_order_status() to reconcile it.
        A recently filled bot entry gets a short grace period for the portfolio
        snapshot to catch up.
        """
        if not isinstance(position, dict):
            return False
        if position.get("order_status") == "broker_recovered":
            return True
        if (
            position.get("exit_evaluation_enabled") is False
            and position.get("user_action_required") is True
            and position.get("api_controllable") is False
            and position.get("recovery_source") == "broker_position"
        ):
            return True
        if not position.get("order_id", ""):
            return False

        status = str(position.get("order_status", "")).lower()
        if status not in _TERMINAL_ORDER_STATUSES:
            return True

        if status == "filled" and position.get("bot_opened") is True:
            event_time = self._position_event_time(position)
            if event_time is None:
                return False
            age_minutes = (now_utc() - event_time).total_seconds() / 60.0
            return age_minutes <= _BOT_POSITION_VISIBILITY_GRACE_MINUTES

        return False

    def _position_event_time(self, position: dict) -> Optional[datetime]:
        for key in ("filled_at", "entry_time"):
            value = position.get(key)
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)
            if isinstance(value, str) and value:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
        return None

    def _find_bot_origin_evidence(
        self,
        *,
        symbol: str,
        qty: float,
        notional: float,
    ) -> dict[str, str] | None:
        finder = getattr(self._journal, "find_recent_bot_entry", None)
        if not callable(finder):
            return None
        try:
            evidence = finder(
                symbol,
                qty=qty,
                notional=notional,
                window_seconds=_JOURNAL_REASSOCIATION_WINDOW_SECONDS,
            )
        except Exception as exc:
            logger.warning(f"{symbol}: journal bot-origin scan failed: {exc}")
            return None
        if not evidence or evidence.get("source") == "journal_recent_error":
            return None
        return evidence

    def _build_reassociated_position(
        self,
        *,
        symbol: str,
        pos: Any,
        avg_entry: float,
        qty: float,
        asset_class: str,
        evidence: dict[str, str],
    ) -> dict[str, Any]:
        entry_price = safe_float(evidence.get("fill_price", 0))
        if entry_price <= 0:
            entry_price = safe_float(evidence.get("price", 0))
        if entry_price <= 0:
            entry_price = avg_entry

        market_value = safe_float(getattr(pos, "market_value", 0))
        evidence_notional = safe_float(evidence.get("notional", 0))
        notional = market_value if market_value > 0 else evidence_notional
        if notional <= 0:
            notional = entry_price * qty

        sl_pct = get_cfg("crypto", "stop_loss_pct", default=1.5) / 100.0
        tp_pct = get_cfg("crypto", "take_profit_pct", default=2.5) / 100.0
        entry_time = evidence.get("timestamp") or now_utc()

        return {
            "entry_price": entry_price,
            "qty": qty,
            "notional": notional,
            "stop_loss": entry_price * (1 - sl_pct),
            "take_profit": entry_price * (1 + tp_pct),
            "strategy": evidence.get("strategy", "unknown"),
            "asset_class": asset_class,
            "order_id": evidence.get("order_id", ""),
            "client_order_id": evidence.get("client_order_id", ""),
            "intent_key": evidence.get("intent_key", ""),
            "order_status": "filled",
            "raw_order_status": evidence.get("status", ""),
            "recovery_source": "journal_reassociated",
            "reconciliable": False,
            "bot_origin_evidence": "journal_order_with_matching_qty",
            "api_controllable": False,
            "bot_opened": True,
            "exit_evaluation_enabled": False,
            "counts_toward_exposure": True,
            "user_action_required": True,
            "manual_review_reason": "broker_close_capability_unconfirmed",
            "entry_time": entry_time,
            "side": "buy",
        }

    def monitor(self, session: SessionState) -> None:
        """
        Main polling method. Call this on every main loop iteration.
        Checks all open positions and triggers exits as needed.
        """
        positions = self._broker.get_all_positions()
        self._reconcile_pending_orders(session)

        if not positions:
            # Clean up session state for symbols that are no longer held
            self._remove_stale_session_positions(session, set())
            return

        open_syms = {getattr(p, "symbol", "") for p in positions}

        # Detect abandoned positions (broker has them but session lost track)
        for pos in positions:
            sym = getattr(pos, "symbol", "")
            if sym and sym not in session.open_positions:
                logger.warning(
                    f"ABANDONED POSITION detected: {sym} — not tracked in session. "
                    "Checking local provenance before adopting."
                )
                # Register it so we can manage it.
                # avg_entry_price is Alpaca-specific; Coinbase positions expose
                # current_price only — use it as a conservative entry estimate.
                avg_entry = safe_float(getattr(pos, "avg_entry_price", 0))
                if avg_entry <= 0:
                    avg_entry = safe_float(getattr(pos, "current_price", 0))
                qty = safe_float(getattr(pos, "qty", 0))
                ac = _detect_asset_class(sym)
                observed_notional = safe_float(getattr(pos, "market_value", 0))
                if observed_notional <= 0:
                    observed_notional = avg_entry * qty

                if _external_inventory_record_for_symbol(sym):
                    _write_external_inventory_observation(
                        sym,
                        qty=qty,
                        observed_notional=observed_notional,
                    )
                    logger.info(
                        f"external_inventory_observed: {sym} seen at broker but classified "
                        "external/staked/non-bot inventory; not rehydrating into active open_positions"
                    )
                    continue

                evidence = self._find_bot_origin_evidence(
                    symbol=sym,
                    qty=qty,
                    notional=avg_entry * qty,
                )
                if evidence:
                    session.open_positions[sym] = self._build_reassociated_position(
                        symbol=sym,
                        pos=pos,
                        avg_entry=avg_entry,
                        qty=qty,
                        asset_class=ac,
                        evidence=evidence,
                    )
                    self._journal.log_warning(
                        symbol=sym,
                        warning=(
                            "Broker position re-associated with bot-origin journal "
                            "evidence; broker close capability remains unconfirmed"
                        ),
                        mode=self._mode,
                    )
                    logger.warning(
                        f"state_normalize: {sym} re-associated from journal evidence "
                        f"order_id={evidence.get('order_id', '')} "
                        "(api_controllable=False, exit_evaluation_enabled=False, "
                        "counts_toward_exposure=True, user_action_required=True)"
                    )
                    get_event_store().record_event(
                        event_type="bot_origin_position_reassociated",
                        severity="warning",
                        asset_class=ac,
                        strategy=session.open_positions[sym].get("strategy", "unknown"),
                        symbol=sym,
                        payload={
                            "notional": session.open_positions[sym].get("notional", 0.0),
                            "order_id": evidence.get("order_id", ""),
                            "client_order_id": evidence.get("client_order_id", ""),
                            "api_controllable": False,
                            "exit_evaluation_enabled": False,
                            "counts_toward_exposure": True,
                            "user_action_required": True,
                        },
                        source_component="position_manager",
                        source_file="position_manager.py",
                    )
                else:
                    self._journal.log_warning(
                        symbol=sym,
                        warning="Pre-existing position adopted as broker_recovered — manual review required",
                        mode=self._mode,
                    )
                    sl_pct = get_cfg("crypto", "stop_loss_pct", default=1.5) / 100.0
                    tp_pct = get_cfg("crypto", "take_profit_pct", default=2.5) / 100.0
                    session.open_positions[sym] = {
                        "entry_price": avg_entry,
                        "qty": qty,
                        "notional": avg_entry * qty,
                        "stop_loss": avg_entry * (1 - sl_pct),
                        "take_profit": avg_entry * (1 + tp_pct),
                        "strategy": "recovered",
                        "asset_class": ac,
                        "order_id": "",
                        # broker_recovered: position confirmed at broker but NOT
                        # placed by this bot session.  No order_id to poll.
                        # Explicit classification so reconcile.sh and any log
                        # reader can answer key state questions at a glance.
                        "order_status": "broker_recovered",
                        "recovery_source": "broker_position",
                        "reconciliable": False,
                        "api_controllable": False,          # cannot close via Advanced Trade API
                        "bot_opened": False,
                        "exit_evaluation_enabled": False,   # skip stop/TP/max-hold evaluation
                        "counts_toward_exposure": True,     # blocks new entries via exposure guard
                        "user_action_required": True,       # human must resolve
                        "entry_time": now_utc(),  # unknown real entry time
                        "side": "buy",
                    }
                    logger.info(
                        f"state_normalize: recovered {sym} no bot-origin evidence "
                        "marked broker_recovered "
                        "(api_controllable=False, exit_evaluation_enabled=False, "
                        "counts_toward_exposure=True, user_action_required=True)"
                    )
                    get_event_store().record_event(
                        event_type="broker_recovered_position_detected",
                        severity="warning",
                        asset_class=ac,
                        strategy="recovered",
                        symbol=sym,
                        payload={
                            "notional": avg_entry * qty,
                            "api_controllable": False,
                            "exit_evaluation_enabled": False,
                            "counts_toward_exposure": True,
                            "user_action_required": True,
                        },
                        source_component="position_manager",
                        source_file="position_manager.py",
                    )
                save_positions(session.open_positions)

        # Clean up session positions that are no longer in broker
        self._remove_stale_session_positions(session, open_syms)

        # Evaluate each open position for exit conditions
        for pos in positions:
            sym = getattr(pos, "symbol", "")
            if not sym:
                continue
            try:
                self._evaluate_position(pos, session)
            except Exception as e:
                logger.error(f"PositionManager error evaluating {sym}: {e}")

        # Force-flat non-crypto positions before market close
        self._check_force_flat(positions, session)

    def _backfill_missing_order_status(self, session: SessionState) -> None:
        """
        Startup-only: poll the broker for any position that has a real
        order_id but a non-terminal order_status (including "pending_new"
        injected by load_saved_positions() for pre-patch entries).

        Updates position fields in-place:
          order_status, raw_order_status, fill_price, filled_size,
          total_fees, filled_at, settled, entry_price (corrected), qty.

        This is a no-op when:
          - The broker doesn't implement get_order_status() (e.g. BrokerAlpaca)
          - All positions are already in a terminal state
          - A position has no order_id (recovered/manual positions)
        """
        get_order_status = getattr(self._broker, "get_order_status", None)
        if get_order_status is None:
            return

        candidates = [
            (sym, pos)
            for sym, pos in session.open_positions.items()
            if pos.get("order_status") not in _TERMINAL_ORDER_STATUSES
            and pos.get("order_id", "")
        ]
        if not candidates:
            return

        logger.info(
            f"_backfill_missing_order_status: polling {len(candidates)} "
            "position(s) with non-terminal order_status"
        )

        for sym, pos in candidates:
            order_id = pos["order_id"]
            try:
                status_info = get_order_status(order_id)
            except Exception as e:
                logger.warning(f"_backfill_missing_order_status({sym}): {e}")
                continue

            if not status_info:
                # API returned nothing — leave as pending_new for next poll
                logger.warning(
                    f"_backfill_missing_order_status({sym}): empty response "
                    f"for order_id={order_id} — will retry in monitor()"
                )
                continue

            normalized   = status_info.get("normalized_status", "unknown")
            raw_status   = status_info.get("raw_status", "")
            fill_price   = safe_float(status_info.get("average_filled_price", 0))
            fill_size    = safe_float(status_info.get("filled_size", 0))
            fees         = safe_float(status_info.get("total_fees", 0))
            filled_at    = status_info.get("last_fill_time", "")
            settled      = status_info.get("settled", False)

            pos["order_status"]     = normalized
            pos["raw_order_status"] = raw_status

            if normalized == "filled":
                pos["fill_price"]  = fill_price if fill_price > 0 else pos.get("entry_price", 0)
                pos["filled_size"] = fill_size  if fill_size  > 0 else pos.get("qty", 0)
                pos["total_fees"]  = fees
                pos["filled_at"]   = filled_at
                pos["settled"]     = settled
                # Correct entry_price / qty with actual fill data
                if fill_price > 0:
                    pos["entry_price"] = fill_price
                if fill_size > 0:
                    pos["qty"] = fill_size

            logger.info(
                f"_backfill_missing_order_status({sym}): order_id={order_id} "
                f"raw={raw_status} → {normalized} | "
                f"fill_price={fill_price} filled_size={fill_size} fees={fees}"
            )

    def _reconcile_pending_orders(self, session: SessionState) -> None:
        """
        For every tracked position whose order_status is "pending_new", poll
        the broker to get the actual fill outcome and update session state.

        - filled   → update entry_price/qty/fees with real fill data, mark
                     order_status="filled" so exit logic activates next loop
        - canceled / rejected / expired → remove position from session and log
        - open / unknown → leave as-is, will be polled again next loop

        This is a no-op for:
          • Positions with no order_id (recovered/manual positions)
          • Positions already at order_status != "pending_new"
          • Brokers that don't implement get_order_status() (e.g. BrokerAlpaca)
          • dry_run / paper positions (order_status == "dry_run_simulated")
        """
        get_order_status = getattr(self._broker, "get_order_status", None)
        if get_order_status is None:
            return  # broker doesn't support order polling

        # Poll any position whose order_status is not yet terminal — this
        # catches "pending_new", "open", "unknown", and None/missing.
        # _backfill_missing_order_status() handles the startup case; this
        # loop handles ongoing polling until the status resolves.
        pending = [
            (sym, pos)
            for sym, pos in session.open_positions.items()
            if pos.get("order_status") not in _TERMINAL_ORDER_STATUSES
            and pos.get("order_id", "")
        ]
        if not pending:
            return

        changed = False
        to_remove: list[str] = []

        for sym, pos in pending:
            order_id = pos["order_id"]
            try:
                status_info = get_order_status(order_id)
            except Exception as e:
                logger.warning(f"_reconcile_pending_orders({sym}): {e}")
                continue

            if not status_info:
                continue

            normalized = status_info.get("normalized_status", "")

            if normalized == "filled":
                fill_price = safe_float(status_info.get("average_filled_price", 0))
                fill_size  = safe_float(status_info.get("filled_size", 0))
                fees       = safe_float(status_info.get("total_fees", 0))
                filled_at  = status_info.get("last_fill_time", "")
                settled    = status_info.get("settled", False)

                # Update position with confirmed fill data; entry_price and qty
                # are overwritten with actual values so exit logic is accurate.
                pos["order_status"]  = "filled"
                pos["fill_price"]    = fill_price if fill_price > 0 else pos.get("entry_price", 0)
                pos["filled_size"]   = fill_size  if fill_size  > 0 else pos.get("qty", 0)
                pos["total_fees"]    = fees
                pos["filled_at"]     = filled_at
                pos["settled"]       = settled
                if fill_price > 0:
                    pos["entry_price"] = fill_price
                if fill_size > 0:
                    pos["qty"] = fill_size

                logger.info(
                    f"ORDER RECONCILED — FILLED: {sym} | order_id={order_id} "
                    f"fill_price={fill_price} filled_size={fill_size} "
                    f"fees={fees} settled={settled} filled_at={filled_at}"
                )

                # P2-011H OPT-IN DRY-RUN CAPTURE SEAM (disabled by default)
                # This block is inert unless dry_run_capture=True was passed to __init__.
                # It proves the exact location in the real entry flow where we can
                # fetch fills and run reconciliation without affecting any decisions.
                if getattr(self, "_dry_run_capture", False):
                    self._maybe_dry_run_capture_entry(sym, order_id, status_info)

                self._journal.log_warning(
                    symbol=sym,
                    warning=(
                        f"Order confirmed FILLED: order_id={order_id} "
                        f"fill_price={fill_price} filled_size={fill_size} "
                        f"total_fees={fees} settled={settled} filled_at={filled_at}"
                    ),
                    mode=self._mode,
                )
                changed = True

            elif normalized in ("canceled", "rejected", "expired"):
                logger.warning(
                    f"ORDER RECONCILED — {normalized.upper()}: {sym} | "
                    f"order_id={order_id} raw={status_info.get('raw_status', '')} "
                    "— removing position from session"
                )
                self._journal.log_warning(
                    symbol=sym,
                    warning=(
                        f"Order {normalized}: order_id={order_id} "
                        f"raw_status={status_info.get('raw_status', '')} "
                        "— position removed from tracking"
                    ),
                    mode=self._mode,
                )
                to_remove.append(sym)
                changed = True

            else:
                # open / unknown — still waiting; log at DEBUG only
                logger.debug(
                    f"_reconcile_pending_orders({sym}): still "
                    f"{normalized} ({status_info.get('raw_status', '')})"
                )

        for sym in to_remove:
            session.open_positions.pop(sym, None)

        if changed:
            save_positions(session.open_positions)

    def _evaluate_position(self, pos: Any, session: SessionState) -> None:
        sym = getattr(pos, "symbol", "")
        tracked = session.open_positions.get(sym, {})

        # Do not apply stop-loss / take-profit until the entry order is confirmed
        # filled.  Reconciliation happens in _reconcile_pending_orders() which
        # runs earlier in the same monitor() call.
        if tracked.get("order_status") == "pending_new":
            logger.debug(
                f"{sym}: entry order still pending_new — deferring exit evaluation"
            )
            return

        if tracked.get("exit_evaluation_enabled") is False:
            logger.debug(
                f"{sym}: exit_evaluation_enabled=False — skip exit evaluation"
            )
            return

        # broker_recovered positions live in the consumer Coinbase wallet — we
        # cannot close them via the Advanced Trade API.  Skip all exit evaluation
        # so we never attempt a close (which would fail, increment close_failure_count,
        # and eventually drop-then-readopt the position in an infinite loop).
        # The exposure guard keeps new entries blocked while these exist; they
        # leave tracking only after explicit operator cleanup.
        if tracked.get("order_status") == "broker_recovered":
            logger.debug(
                f"{sym}: broker_recovered — skip exit evaluation (consumer wallet, cannot close via API)"
            )
            return

        current_price = safe_float(getattr(pos, "current_price", 0))
        # avg_entry_price is Alpaca-specific; Coinbase positions don't carry it.
        # Fall back to the tracked entry_price we stored at position registration.
        avg_entry = safe_float(getattr(pos, "avg_entry_price", 0))
        if avg_entry <= 0:
            avg_entry = safe_float(tracked.get("entry_price", 0))
        qty = safe_float(getattr(pos, "qty", 0))
        unrealized_pnl = safe_float(getattr(pos, "unrealized_pl", 0))
        side = tracked.get("side", "buy")

        if current_price <= 0 or avg_entry <= 0:
            logger.warning(f"{sym}: invalid price data from broker, skipping exit check")
            return

        stop_loss = tracked.get("stop_loss", 0)
        take_profit = tracked.get("take_profit", 0)
        entry_time: Optional[datetime] = tracked.get("entry_time")
        asset_class = tracked.get("asset_class", "crypto")
        strategy = tracked.get("strategy", "unknown")

        exit_reason: Optional[str] = None

        # Exit policy branching
        if get_cfg("crypto", "mfe_mae_exits_enabled", default=False):
            if self._mfe_mae_params_cache is None:
                try:
                    from mfe_mae_exit_analysis import generate_exit_parameter_cache
                    price_path = Path("logs/coinbase_price_path.csv").resolve()
                    journal_path = Path("journal_coinbase_crypto.csv").resolve()
                    self._mfe_mae_params_cache = generate_exit_parameter_cache(price_path, journal_path)
                except Exception as e:
                    logger.error(f"Failed to load MFE/MAE parameters: {e}")
                    self._mfe_mae_params_cache = {}

            # Cache lookup
            sym_strat = f"{sym}_{strategy}"
            sym_all = f"{sym}_ALL"
            all_strat = f"ALL_{strategy}"

            if sym_strat in self._mfe_mae_params_cache:
                params = self._mfe_mae_params_cache[sym_strat]
            elif sym_all in self._mfe_mae_params_cache:
                params = self._mfe_mae_params_cache[sym_all]
            elif all_strat in self._mfe_mae_params_cache:
                params = self._mfe_mae_params_cache[all_strat]
            else:
                params = self._mfe_mae_params_cache.get("GLOBAL_FALLBACK")

            if params and params.is_valid:
                from exit_policy_mfe_mae import decide_exit
                elapsed_minutes = (now_utc() - entry_time).total_seconds() / 60.0 if entry_time else 0.0

                # We format the position dict for the policy
                policy_pos = {
                    "entry_price": avg_entry,
                    "side": side,
                }
                action, reason = decide_exit(policy_pos, current_price, elapsed_minutes, params)
                if action and reason:
                    exit_reason = reason
        else:
            # 1. Stop-loss
            if stop_loss > 0:
                if side == "buy" and current_price <= stop_loss:
                    exit_reason = f"stop-loss hit @ {current_price:.4f} (stop={stop_loss:.4f})"
                elif side == "short" and current_price >= stop_loss:
                    exit_reason = f"stop-loss hit (short) @ {current_price:.4f} (stop={stop_loss:.4f})"

            # 2. Take-profit
            if exit_reason is None and take_profit > 0:
                if side == "buy" and current_price >= take_profit:
                    exit_reason = f"take-profit hit @ {current_price:.4f} (tp={take_profit:.4f})"
                elif side == "short" and current_price <= take_profit:
                    exit_reason = f"take-profit hit (short) @ {current_price:.4f} (tp={take_profit:.4f})"

            # 3. Max holding time
            if exit_reason is None and entry_time is not None:
                max_minutes = get_cfg("crypto", "max_position_minutes", default=90)
                age_minutes = (now_utc() - entry_time).total_seconds() / 60.0
                if asset_class == "crypto" and age_minutes >= max_minutes:
                    exit_reason = f"max hold time {max_minutes}min exceeded ({age_minutes:.1f}min held)"

        # 4. Options: never hold through expiration (handled upstream, but belt+suspenders)
        if exit_reason is None and asset_class == "option":
            if get_cfg("options", "never_hold_through_expiration", default=True):
                # Expiration check would require options chain data; log warning
                logger.debug(f"{sym}: options expiration check — ensure position is managed")

        if exit_reason:
            self._execute_exit(sym, qty, avg_entry, current_price, unrealized_pnl,
                               strategy, asset_class, exit_reason, session)

    def _execute_exit(
        self,
        sym: str,
        qty: float,
        entry_price: float,
        exit_price: float,
        pnl_usd: float,      # broker-reported unrealized P/L or 0 if unavailable
        strategy: str,
        asset_class: str,
        reason: str,
        session: SessionState,
    ) -> None:
        # Gross P/L from price movement alone
        gross_pnl = (exit_price - entry_price) * qty if entry_price > 0 and qty > 0 else pnl_usd
        pnl_pct_gross = (exit_price - entry_price) / entry_price * 100.0 if entry_price > 0 else 0.0

        # Estimate fees: entry + exit, using config fee rates
        entry_fee_rate = get_cfg("crypto", "fee_entry_pct", default=0.006) if asset_class == "crypto" else 0.0
        exit_fee_rate = get_cfg("crypto", "fee_exit_pct", default=0.006) if asset_class == "crypto" else 0.0
        entry_notional = entry_price * qty if entry_price > 0 and qty > 0 else 0.0
        exit_notional = exit_price * qty if exit_price > 0 and qty > 0 else 0.0
        fees_paid = (entry_notional * entry_fee_rate) + (exit_notional * exit_fee_rate)

        # Net P/L = gross − estimated fees
        net_pnl = gross_pnl - fees_paid
        net_pnl_pct = net_pnl / entry_notional * 100.0 if entry_notional > 0 else 0.0

        logger.info(
            f"EXIT triggered: {sym} | {reason} | "
            f"entry={entry_price:.4f} exit={exit_price:.4f} qty={qty:.6f} | "
            f"gross={gross_pnl:+.4f} fees=-{fees_paid:.4f} net={net_pnl:+.4f} ({net_pnl_pct:+.2f}%)"
        )

        order = self._broker.close_position(sym)

        if order is None:
            # ----------------------------------------------------------------
            # Broker rejected the close order.  Do NOT record P/L or remove
            # the position — that would create phantom losses and corrupt the
            # daily stats / consecutive-loss counter.
            #
            # Instead, track failure count per position.  After max_close_failures
            # consecutive failed closes, the position is dropped from tracking
            # WITHOUT recording any P/L (it's unrecoverable via the API).
            # ----------------------------------------------------------------
            tracked = session.open_positions.get(sym, {})
            failures = tracked.get("close_failure_count", 0) + 1
            if tracked:
                tracked["close_failure_count"] = failures
            max_failures = int(get_cfg("global_risk", "max_close_failures", default=3))
            logger.warning(
                f"EXIT BLOCKED: {sym} — close_position() returned None "
                f"(attempt {failures}/{max_failures}). Trigger was: {reason}"
            )
            if failures >= max_failures:
                logger.error(
                    f"{sym}: {failures} consecutive close failures — "
                    "position is unrecoverable via API. Dropping from tracking "
                    "without recording P/L."
                )
                self._journal.log_warning(
                    symbol=sym,
                    warning=(
                        f"Position dropped after {failures} failed close attempts "
                        f"(unrecoverable). Last trigger: {reason}. No P/L recorded."
                    ),
                    mode=self._mode,
                )
                session.open_positions.pop(sym, None)
            # Always persist: failure count survives bot restarts; drop persists too.
            save_positions(session.open_positions)
            return  # Do NOT journal exit or record P/L

        # Close order accepted by broker — journal and record P/L.
        self._journal.log_exit(
            symbol=sym,
            asset_class=asset_class,
            strategy=strategy,
            exit_price=exit_price,
            entry_price=entry_price,
            qty=qty,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            pnl_usd=net_pnl,
            pnl_pct=net_pnl_pct,
            reason=reason,
            order_id=getattr(order, "id", ""),
            client_order_id=getattr(order, "client_order_id", ""),
            mode=self._mode,
        )

        # P2-011H OPT-IN DRY-RUN CAPTURE SEAM (disabled by default)
        # Proves the exact location in the real exit flow (after close_position)
        # where we can fetch the exit order status + fills and run reconciliation.
        if getattr(self, "_dry_run_capture", False):
            exit_order_id = getattr(order, "id", "")
            if exit_order_id:
                self._maybe_dry_run_capture_exit(sym, exit_order_id)

        # Session state uses net P/L (after fees) — the accurate figure
        if net_pnl >= 0:
            session.record_win(net_pnl)
        else:
            session.record_loss(net_pnl)
        session.record_exit_event()

        # Remove from tracked positions and persist
        session.open_positions.pop(sym, None)
        save_positions(session.open_positions)

        # Halt check after recording P/L
        max_loss = get_cfg("global_risk", "max_daily_loss_usd", default=2.0)
        if session.daily_realized_pnl <= -abs(max_loss):
            session.halt(
                f"Daily loss limit reached: ${session.daily_realized_pnl:.2f}"
            )

    # =====================================================================
    # P2-011H OPT-IN DRY-RUN CAPTURE SEAM (completely disabled by default)
    # These methods exist only to prove the exact location in the real
    # entry/exit flow where we can fetch order status + historical fills
    # and run the P2-011G capture/reconciliation helpers.
    #
    # - Never enabled unless dry_run_capture=True is explicitly passed to __init__.
    # - Perform no writes, no side effects on trading state or P/L.
    # - Intended for test-only / dry-run proof use.
    # =====================================================================

    def _maybe_dry_run_capture_entry(self, sym: str, order_id: str, status_info: dict) -> None:
        """Inert entry capture seam. Only runs when _dry_run_capture=True."""
        if not getattr(self, "_dry_run_capture", False):
            return
        try:
            from coinbase_entry_exit_capture import capture_entry
            fills = []
            if hasattr(self._broker, "get_historical_fills"):
                try:
                    fills = self._broker.get_historical_fills(order_id=order_id) or []
                except Exception:
                    fills = []
            cap = capture_entry(status_info or {}, fills, symbol=sym, account_mode=self._mode)
            self._dry_run_captures.append(cap)
            logger.info(f"DRY_RUN_CAPTURE[entry]: {sym} logger_ready={cap.logger_ready} blocking={cap.blocking_reasons}")
        except Exception as e:
            logger.debug(f"DRY_RUN_CAPTURE entry error (non-fatal for proof): {e}")

    def _maybe_dry_run_capture_exit(self, sym: str, exit_order_id: str) -> None:
        """Inert exit capture seam. Only runs when _dry_run_capture=True."""
        if not getattr(self, "_dry_run_capture", False):
            return
        try:
            from coinbase_entry_exit_capture import capture_exit
            status_info = {}
            if hasattr(self._broker, "get_order_status"):
                try:
                    status_info = self._broker.get_order_status(exit_order_id) or {}
                except Exception:
                    status_info = {}
            fills = []
            if hasattr(self._broker, "get_historical_fills"):
                try:
                    fills = self._broker.get_historical_fills(order_id=exit_order_id) or []
                except Exception:
                    fills = []
            cap = capture_exit(status_info, fills, symbol=sym, account_mode=self._mode)
            self._dry_run_captures.append(cap)
            logger.info(f"DRY_RUN_CAPTURE[exit]: {sym} logger_ready={cap.logger_ready} blocking={cap.blocking_reasons}")
        except Exception as e:
            logger.debug(f"DRY_RUN_CAPTURE exit error (non-fatal for proof): {e}")

    def _check_force_flat(self, positions: list[Any], session: SessionState) -> None:
        """Close all non-crypto equity/options positions before market close."""
        if not get_cfg("global_risk", "force_flat_before_market_close", default=True):
            return

        force_flat_time_str = get_cfg("global_risk", "force_flat_time", default="14:55")
        try:
            local = now_local()
            h, m = map(int, force_flat_time_str.split(":"))
            force_flat_time = local.replace(hour=h, minute=m, second=0, microsecond=0)

            if local < force_flat_time:
                return  # Not time yet

            for pos in positions:
                sym = getattr(pos, "symbol", "")
                tracked = session.open_positions.get(sym, {})
                asset_class = tracked.get("asset_class", _detect_asset_class(sym))

                if asset_class in ("equity", "option"):
                    qty = safe_float(getattr(pos, "qty", 0))
                    avg_entry = safe_float(getattr(pos, "avg_entry_price", 0))
                    current_price = safe_float(getattr(pos, "current_price", avg_entry))
                    pnl_usd = safe_float(getattr(pos, "unrealized_pl", 0))

                    logger.warning(f"FORCE FLAT: closing {sym} before market close")
                    self._execute_exit(
                        sym=sym, qty=qty, entry_price=avg_entry,
                        exit_price=current_price, pnl_usd=pnl_usd,
                        strategy=tracked.get("strategy", "unknown"),
                        asset_class=asset_class,
                        reason=f"force-flat before market close ({force_flat_time_str})",
                        session=session,
                    )
        except Exception as e:
            logger.error(f"force_flat error: {e}")

    def close_all_for_halt(self, session: SessionState) -> None:
        """Emergency: close everything when a halt condition is triggered."""
        logger.critical("HALT: closing all positions via emergency liquidation")
        positions = self._broker.get_all_positions()
        for pos in positions:
            sym = getattr(pos, "symbol", "")
            if sym:
                self._broker.close_position(sym)
                self._journal.log_error(
                    symbol=sym,
                    error=f"Position closed during emergency halt: {session.halt_reason}",
                    mode=self._mode,
                )
        session.open_positions.clear()


def _detect_asset_class(symbol: str) -> str:
    """Best-guess asset class from symbol format."""
    if "/" in symbol:
        return "crypto"
    if len(symbol) > 6 and symbol[0].isalpha():
        return "option"
    return "equity"
