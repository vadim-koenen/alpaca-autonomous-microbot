"""
order_manager.py — Dedup-protected order router.

Responsibilities:
  1. Accept an approved TradeProposal (already cleared by risk manager)
  2. Check for open orders/positions to prevent duplicates
  3. Calculate the exact limit price and qty to submit
  4. Call broker_alpaca to place the order
  5. Record the outcome in the journal
  6. Increment session state counters

The order manager ONLY calls broker.place_* after receiving risk manager approval.
It never bypasses risk_manager.check().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from broker_alpaca import BrokerAlpaca
from journal import Journal
from memory.event_store import get_event_store
from risk_manager import TradeProposal
from utils import (
    build_client_order_id,
    build_order_intent_key,
    get_broker_name,
    get_cfg,
    get_mode,
    now_utc,
    save_positions,
)

logger = logging.getLogger("order_manager")


@dataclass
class SessionState:
    """Mutable trading session counters passed around the main loop."""
    daily_trade_count: int = 0
    consecutive_losses: int = 0
    daily_realized_pnl: float = 0.0
    api_error_count: int = 0
    # track open positions: symbol -> entry data
    open_positions: dict = field(default_factory=dict)
    halted: bool = False
    halt_reason: str = ""
    last_trade_at: str = ""
    last_exit_at: str = ""
    # ISO date string (YYYY-MM-DD UTC) of the last daily-reset so the main
    # loop can reset per-day counters mid-run without restarting the bot.
    _last_daily_reset_date: str = field(default="", repr=False)

    def record_trade_event(self, timestamp: str | None = None) -> None:
        self.last_trade_at = timestamp or now_utc().isoformat()

    def record_exit_event(self, timestamp: str | None = None) -> None:
        self.last_exit_at = timestamp or now_utc().isoformat()

    def record_win(self, pnl: float) -> None:
        self.consecutive_losses = 0
        self.daily_realized_pnl += pnl
        self.daily_trade_count += 1

    def record_loss(self, pnl: float) -> None:
        self.consecutive_losses += 1
        self.daily_realized_pnl += pnl   # pnl is negative
        self.daily_trade_count += 1

    def record_api_error(self) -> None:
        self.api_error_count += 1

    def halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason
        logger.critical(f"SESSION HALTED: {reason}")

    def maybe_daily_reset(self) -> bool:
        """
        Reset per-day counters if UTC date has rolled over since last reset.

        Called at the top of every main-loop cycle.  Returns True when a
        reset was performed so the caller can log it.

        Resets: daily_trade_count, consecutive_losses, daily_realized_pnl,
                api_error_count, halted (day-end halt only — NOT a hard halt
                like equity-below-floor; those require a restart).
        Does NOT reset: open_positions, halt_reason, halted if the halt was
                        a permanent/equity-floor halt (checked by caller).
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_daily_reset_date == today:
            return False
        self._last_daily_reset_date = today
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.daily_realized_pnl = 0.0
        self.api_error_count = 0
        # Clear a soft daily halt (stop-after-N-losses) but not a hard halt
        # (equity floor, kill switch, etc.).  Distinguish by halt_reason prefix.
        if self.halted and self.halt_reason.startswith("consecutive loss limit"):
            self.halted = False
            self.halt_reason = ""
        return True


class OrderManager:
    def __init__(self, broker: BrokerAlpaca, journal: Journal) -> None:
        self._broker = broker
        self._journal = journal
        self._mode = get_mode()

    def execute(
        self,
        proposal: TradeProposal,
        session: SessionState,
        account_equity: float,
        buying_power: float,
        open_positions: int,
    ) -> Optional[Any]:
        """
        Place an order for an already-approved proposal.
        Returns the order object or None on failure/dry-run.

        This method is the ONLY code path that calls broker.place_*.
        """
        symbol = proposal.symbol
        mode = self._mode
        broker_name = get_broker_name()
        purpose = str(proposal.meta.get("order_purpose", "entry"))
        intent_key = build_order_intent_key(
            broker=broker_name,
            strategy=proposal.strategy,
            asset_class=proposal.asset_class,
            symbol=symbol,
            side=proposal.side,
            purpose=purpose,
        )

        duplicate = self._check_duplicate_intent(
            proposal=proposal,
            session=session,
            intent_key=intent_key,
            purpose=purpose,
        )
        if duplicate:
            self._record_blocked_intent(
                proposal=proposal,
                intent_key=intent_key,
                purpose=purpose,
                reason=duplicate["reason"],
                source=duplicate["source"],
                existing_client_order_id=duplicate.get("existing_client_order_id", ""),
                mode=mode,
            )
            return None

        # Calculate order parameters
        limit_price, qty, notional = self._calculate_order_params(proposal)
        if limit_price <= 0 or (qty <= 0 and notional <= 0):
            reason = f"invalid computed order params: limit={limit_price} qty={qty} notional={notional}"
            logger.error(f"ORDER BLOCKED: {reason}")
            self._journal.log_skip(
                symbol=symbol, asset_class=proposal.asset_class,
                strategy=proposal.strategy, reason=reason, mode=mode,
                intent_key=intent_key,
            )
            return None

        client_order_id = build_client_order_id(
            broker=broker_name,
            strategy=proposal.strategy,
            symbol=symbol,
            side=proposal.side,
            purpose=purpose,
        )
        logger.info(
            f"ORDER PREVIEW: {proposal.side.upper()} {symbol} "
            f"type={proposal.order_type} qty={qty:.8f} notional=${notional:.4f} "
            f"limit={limit_price:.8f} client_order_id={client_order_id} "
            f"intent_key={intent_key}"
        )
        self._journal.log_order_preview(
            symbol=symbol,
            asset_class=proposal.asset_class,
            strategy=proposal.strategy,
            action=proposal.side.upper(),
            client_order_id=client_order_id,
            intent_key=intent_key,
            qty=qty,
            notional=notional,
            price=proposal.price,
            order_type=proposal.order_type,
            bid=proposal.bid,
            ask=proposal.ask,
            spread_pct=proposal.meta.get("spread_pct", 0.0),
            confidence=proposal.confidence,
            equity=account_equity,
            buying_power=buying_power,
            open_positions=open_positions,
            daily_trade_count=session.daily_trade_count,
            consecutive_losses=session.consecutive_losses,
            mode=mode,
        )
        get_event_store().record_order(
            status="preview",
            client_order_id=client_order_id,
            intent_key=intent_key,
            broker=broker_name,
            asset_class=proposal.asset_class,
            strategy=proposal.strategy,
            symbol=symbol,
            side=proposal.side,
            purpose=purpose,
            notional=notional,
            qty=qty,
            payload={"order_type": proposal.order_type, "limit_price": limit_price},
            event_type="order_preview",
            source_component="order_manager",
            source_file="order_manager.py",
        )

        # Place the order
        order = None
        error_msg = ""
        try:
            if proposal.order_type == "limit":
                order = self._broker.place_limit_order(
                    symbol=symbol,
                    side=proposal.side,
                    qty=qty,
                    limit_price=limit_price,
                    time_in_force="gtc",
                    asset_class=proposal.asset_class,
                    client_order_id=client_order_id,
                )
            elif proposal.order_type == "market":
                order = self._broker.place_market_order(
                    symbol=symbol,
                    side=proposal.side,
                    notional=notional if qty == 0 else None,
                    qty=qty if qty > 0 else None,
                    time_in_force="gtc",
                    client_order_id=client_order_id,
                )
            else:
                reason = f"unsupported order_type: {proposal.order_type}"
                logger.error(f"ORDER BLOCKED: {reason}")
                self._journal.log_skip(
                    symbol=symbol, asset_class=proposal.asset_class,
                    strategy=proposal.strategy, reason=reason, mode=mode,
                    intent_key=intent_key,
                )
                return None

        except Exception as e:
            error_msg = str(e)
            session.record_api_error()
            logger.error(f"Order placement exception for {symbol}: {e}")
            self._record_uncertain_order_state(
                proposal=proposal,
                client_order_id=client_order_id,
                intent_key=intent_key,
                purpose=purpose,
                error=error_msg,
                mode=mode,
            )

            # Halt if error rate is too high
            max_errors = get_cfg("global_risk", "max_api_errors_before_halt", default=10)
            if session.api_error_count >= max_errors:
                session.halt(f"API error count {session.api_error_count} >= {max_errors}")

        if order is None and not error_msg:
            # broker returned None without exception (dry_run or soft block)
            error_msg = "broker returned None (dry_run or blocked)"
            self._record_uncertain_order_state(
                proposal=proposal,
                client_order_id=client_order_id,
                intent_key=intent_key,
                purpose=purpose,
                error=error_msg,
                mode=mode,
            )

        order_id = getattr(order, "id", "") if order else ""
        returned_client_order_id = (
            getattr(order, "client_order_id", client_order_id) if order else client_order_id
        )
        status = getattr(order, "status", "failed") if order else "failed"

        self._journal.log_order(
            symbol=symbol,
            asset_class=proposal.asset_class,
            strategy=proposal.strategy,
            action=proposal.side.upper(),
            order_id=order_id,
            client_order_id=returned_client_order_id,
            intent_key=intent_key,
            status=status,
            decision="PLACED" if order is not None else "BLOCKED",
            reason="" if order is not None else error_msg,
            qty=qty,
            notional=notional,
            price=proposal.price,
            order_type=proposal.order_type,
            bid=proposal.bid,
            ask=proposal.ask,
            spread_pct=proposal.meta.get("spread_pct", 0.0),
            confidence=proposal.confidence,
            equity=account_equity,
            buying_power=buying_power,
            open_positions=open_positions,
            daily_trade_count=session.daily_trade_count,
            consecutive_losses=session.consecutive_losses,
            mode=mode,
            error=error_msg,
        )

        if order is not None:
            session.daily_trade_count += 1
            session.record_trade_event()
            # Track in session state for position manager to pick up
            session.open_positions[symbol] = {
                "entry_price": limit_price,
                "qty": qty,
                "notional": notional,
                "stop_loss": proposal.stop_loss_price,
                "take_profit": proposal.take_profit_price,
                "strategy": proposal.strategy,
                "asset_class": proposal.asset_class,
                "order_id": order_id,
                "client_order_id": returned_client_order_id,
                "intent_key": intent_key,
                "order_purpose": purpose,
                # order_status starts as pending_new; position_manager will poll
                # get_order_status() on each loop and update to "filled",
                # "canceled", "rejected", or "expired" before activating exits.
                # dry_run orders use "dry_run_simulated" and skip polling.
                "order_status": getattr(order, "status", "pending_new"),
                "counts_toward_exposure": True,
                "api_controllable": True,
                "bot_opened": True,
                "exit_evaluation_enabled": True,
                "user_action_required": False,
                "entry_time": now_utc(),
                "side": proposal.side,
            }
            # Persist so state survives a restart
            save_positions(session.open_positions)
            logger.info(
                f"ORDER ACCEPTED: {proposal.side.upper()} {symbol} | "
                f"qty={qty:.6f} limit={limit_price:.4f} | "
                f"broker_order_id={order_id} client_order_id={returned_client_order_id}"
            )
            get_event_store().record_order(
                status=status,
                client_order_id=returned_client_order_id,
                broker_order_id=order_id,
                intent_key=intent_key,
                broker=broker_name,
                asset_class=proposal.asset_class,
                strategy=proposal.strategy,
                symbol=symbol,
                side=proposal.side,
                purpose=purpose,
                notional=notional,
                qty=qty,
                payload={"order_type": proposal.order_type, "limit_price": limit_price},
                event_type="order_placed",
                source_component="order_manager",
                source_file="order_manager.py",
            )

        return order

    def _check_duplicate_intent(
        self,
        *,
        proposal: TradeProposal,
        session: SessionState,
        intent_key: str,
        purpose: str,
    ) -> dict[str, str] | None:
        symbol = proposal.symbol
        side = proposal.side.lower()

        for tracked_symbol, tracked in session.open_positions.items():
            if tracked.get("intent_key") == intent_key or tracked_symbol == symbol:
                return {
                    "reason": "duplicate_order_intent_detected",
                    "source": "local_state",
                    "existing_client_order_id": str(tracked.get("client_order_id", "")),
                }

        try:
            open_orders = self._broker.get_open_orders()
        except Exception as exc:
            return {
                "reason": "order_state_uncertain",
                "source": "broker_open_orders",
                "existing_client_order_id": "",
                "error": str(exc),
            }

        broker_error = getattr(self._broker, "last_open_orders_error", "")
        if broker_error:
            return {
                "reason": "order_state_uncertain",
                "source": "broker_open_orders",
                "existing_client_order_id": "",
                "error": broker_error,
            }

        for order in open_orders:
            order_symbol = getattr(order, "symbol", "")
            order_side = str(getattr(order, "side", "")).lower()
            if order_symbol == symbol and (not order_side or order_side == side):
                return {
                    "reason": "duplicate_order_intent_detected",
                    "source": "broker_open_orders",
                    "existing_client_order_id": str(getattr(order, "client_order_id", "")),
                }

        window = int(get_cfg(
            "global_risk",
            "duplicate_order_safety_window_seconds",
            default=900,
        ))
        recent = self._journal.find_recent_order_intent(
            intent_key,
            window_seconds=window,
        )
        if recent and recent.get("source") == "journal_recent_error":
            return {
                "reason": "order_state_uncertain",
                "source": "journal_recent",
                "existing_client_order_id": "",
                "error": recent.get("error", ""),
            }
        if recent:
            return {
                "reason": "duplicate_order_intent_detected",
                "source": "journal_recent",
                "existing_client_order_id": str(recent.get("client_order_id", "")),
            }
        return None

    def _record_blocked_intent(
        self,
        *,
        proposal: TradeProposal,
        intent_key: str,
        purpose: str,
        reason: str,
        source: str,
        existing_client_order_id: str,
        mode: str,
    ) -> None:
        logger.warning(
            f"ENTRY_BLOCKED reason={reason} symbol={proposal.symbol} "
            f"strategy={proposal.strategy} source={source} "
            f"intent_key={intent_key} existing_client_order_id={existing_client_order_id}"
        )
        self._journal.log_skip(
            symbol=proposal.symbol,
            asset_class=proposal.asset_class,
            strategy=proposal.strategy,
            reason=f"{reason} source={source}",
            action=proposal.side.upper(),
            mode=mode,
            intent_key=intent_key,
        )
        get_event_store().record_order(
            status="blocked",
            intent_key=intent_key,
            broker=get_broker_name(),
            asset_class=proposal.asset_class,
            strategy=proposal.strategy,
            symbol=proposal.symbol,
            side=proposal.side,
            purpose=purpose,
            notional=proposal.notional,
            qty=proposal.qty,
            payload={
                "reason": reason,
                "source": source,
                "existing_client_order_id": existing_client_order_id,
            },
            event_type="order_blocked",
            severity="warning",
            source_component="order_manager",
            source_file="order_manager.py",
        )

    def _record_uncertain_order_state(
        self,
        *,
        proposal: TradeProposal,
        client_order_id: str,
        intent_key: str,
        purpose: str,
        error: str,
        mode: str,
    ) -> None:
        logger.warning(
            f"ENTRY_BLOCKED reason=order_state_uncertain symbol={proposal.symbol} "
            f"strategy={proposal.strategy} action=manual_reconciliation_required "
            f"client_order_id={client_order_id} intent_key={intent_key}"
        )
        self._journal.log_skip(
            symbol=proposal.symbol,
            asset_class=proposal.asset_class,
            strategy=proposal.strategy,
            reason="order_state_uncertain manual_reconciliation_required",
            action=proposal.side.upper(),
            mode=mode,
            intent_key=intent_key,
        )
        store = get_event_store()
        store.record_order(
            status="uncertain",
            client_order_id=client_order_id,
            intent_key=intent_key,
            broker=get_broker_name(),
            asset_class=proposal.asset_class,
            strategy=proposal.strategy,
            symbol=proposal.symbol,
            side=proposal.side,
            purpose=purpose,
            notional=proposal.notional,
            qty=proposal.qty,
            payload={"error": error, "manual_reconciliation_required": True},
            event_type="order_state_uncertain",
            severity="error",
            source_component="order_manager",
            source_file="order_manager.py",
        )
        store.record_incident(
            severity="error",
            component="order_manager",
            summary="Order state uncertain after submit attempt",
            details={
                "symbol": proposal.symbol,
                "strategy": proposal.strategy,
                "client_order_id": client_order_id,
                "intent_key": intent_key,
                "error": error,
            },
            broker=get_broker_name(),
            asset_class=proposal.asset_class,
            source_file="order_manager.py",
        )

    def _calculate_order_params(
        self, proposal: TradeProposal
    ) -> tuple[float, float, float]:
        """
        Compute (limit_price, qty, notional) from the proposal.
        For crypto: use notional-based fractional quantity.
        For equities: use notional directly (fractional orders).
        Returns (limit_price, qty, notional).
        """
        limit_price = proposal.limit_price
        notional = proposal.notional

        if limit_price <= 0:
            # Fall back to ask for buys, bid for sells
            if proposal.side in ("buy", "cover"):
                limit_price = proposal.ask
            else:
                limit_price = proposal.bid

        if limit_price <= 0:
            return 0.0, 0.0, 0.0

        # For crypto: compute qty from notional
        if proposal.asset_class == "crypto":
            qty = round(notional / limit_price, 8)
            return limit_price, qty, notional

        # For equities with fractional support: submit by notional
        if get_cfg("equities", "use_fractional_notional", default=True):
            return limit_price, 0.0, notional  # qty=0 means use notional

        # Fallback: compute integer qty
        qty = max(1, int(notional / limit_price))
        return limit_price, float(qty), qty * limit_price
