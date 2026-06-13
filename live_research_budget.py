"""P2-042C pure budget-monitoring and auto-kill decision layer for live research.

This module is completely isolated. It does not touch broker APIs, live order systems,
daemon managers, or perform live mutations. It analyzes configuration and journal evidence
to return a decision: ALLOW, PAUSE, KILL, or FAIL_CLOSED.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from live_research_journal import (
    live_research_journal_fail_closed_reasons,
    update_mfe_mae,
)

# A simplified subset of the policy dict expected from P2-042A
@dataclass(frozen=True)
class ResearchBudgetPolicy:
    live_research_for_data: bool
    live_trading_for_profit: bool
    live_research_approval_present: bool
    approval_text: str
    research_budget_usd: float
    max_daily_research_loss_usd: float
    max_weekly_research_loss_usd: float
    max_single_trade_notional_usd: float
    max_research_trades_per_day: int
    allowed_research_symbols: tuple[str, ...]
    research_mode_expires_at: str


@dataclass(frozen=True)
class ResearchBudgetState:
    total_budget_used_usd: float
    daily_loss_usd: float
    weekly_loss_usd: float
    gross_notional_used_usd: float
    trades_today: int
    prior_kill_events: int
    broker_error_observations: int


@dataclass(frozen=True)
class ResearchKillReason:
    reason: str
    context: str


@dataclass(frozen=True)
class ResearchBudgetDecision:
    decision: str  # "ALLOW", "PAUSE", "KILL", "FAIL_CLOSED"
    reasons: tuple[ResearchKillReason, ...]
    kill_event: Optional[Mapping[str, Any]] = None


def _is_valid_approval(text: str) -> bool:
    """Check if the explicit approval text is present and correctly formatted."""
    if not text:
        return False
    return bool(re.search(r"LIVE_RESEARCH_APPROVED\s+for.*with\s+max\s+loss\s+budget\s+\$\d+", text, re.IGNORECASE))


def _is_expired(expiry_iso: str, now: datetime) -> bool:
    if not expiry_iso:
        return True
    try:
        dt = datetime.fromisoformat(expiry_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    return now >= dt


def summarize_research_budget_usage(
    events: Iterable[Mapping[str, Any]],
    now: datetime
) -> ResearchBudgetState:
    """Compute one-way ratchet budget consumption from journal events.
    
    Losses consume budget. Profits do NOT reduce budget consumption (strictly conservative).
    """
    total_loss = 0.0
    daily_loss = 0.0
    weekly_loss = 0.0
    gross_notional = 0.0
    trades_today = 0
    kill_events = 0
    broker_errors = 0

    now_ts = now.timestamp()
    day_seconds = 86400
    week_seconds = 7 * day_seconds

    for event in events:
        event_type = event.get("event_type")
        timestamp_str = event.get("timestamp_utc", "")
        
        try:
            event_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            event_ts = event_dt.timestamp()
        except ValueError:
            event_ts = 0

        age_seconds = max(0, now_ts - event_ts)
        is_today = age_seconds <= day_seconds
        is_this_week = age_seconds <= week_seconds

        if event_type == "exit_observed":
            # Ratchet logic: only add absolute losses + fees.
            net_pnl = float(event.get("realized_net_pnl_usd") or 0.0)
            fees = float(event.get("realized_fees_usd") or 0.0)
            
            # If net_pnl is negative, we lost money. 
            loss_amount = max(0.0, -net_pnl)
            # If net_pnl is missing or broken, at minimum we incurred fees.
            loss_amount = max(loss_amount, fees)

            total_loss += loss_amount
            if is_today:
                daily_loss += loss_amount
            if is_this_week:
                weekly_loss += loss_amount

        elif event_type == "fill_observed" and event.get("fill_complete"):
            notional = float(event.get("gross_notional_usd") or 0.0)
            gross_notional += notional
            if is_today:
                trades_today += 1

        elif event_type == "kill_switch_triggered":
            kill_events += 1

        elif event_type == "broker_error_observed":
            # Note: This checks journals only, no broker API called
            broker_errors += 1

    return ResearchBudgetState(
        total_budget_used_usd=total_loss,
        daily_loss_usd=daily_loss,
        weekly_loss_usd=weekly_loss,
        gross_notional_used_usd=gross_notional,
        trades_today=trades_today,
        prior_kill_events=kill_events,
        broker_error_observations=broker_errors,
    )


def research_budget_fail_closed_reasons(
    policy: ResearchBudgetPolicy,
    journal_events: Iterable[Mapping[str, Any]],
    requested_symbol: str,
    requested_notional: float,
    now: datetime,
) -> list[ResearchKillReason]:
    """Evaluate configuration/policy boundaries that require absolute fail-closed."""
    reasons = []

    # 1. LIVE_RESEARCH_FOR_DATA must be true
    if not policy.live_research_for_data:
        reasons.append(ResearchKillReason("live_research_disabled", "live_research_for_data is False"))
    
    # 2. LIVE_TRADING_FOR_PROFIT must be false
    if policy.live_trading_for_profit:
        reasons.append(ResearchKillReason("live_profit_trading_enabled", "live_trading_for_profit must be False"))

    # 3. Approval present
    if not policy.live_research_approval_present:
        reasons.append(ResearchKillReason("missing_approval", "live_research_approval_present is False"))

    # 4. Valid approval text
    if not _is_valid_approval(policy.approval_text):
        reasons.append(ResearchKillReason("invalid_approval_phrase", f"Phrase does not match required pattern: {policy.approval_text}"))

    # 5-9. Missing/invalid budget configurations
    if policy.research_budget_usd is None or policy.research_budget_usd <= 0:
        reasons.append(ResearchKillReason("missing_budget", "research_budget_usd is missing or invalid"))
    if policy.max_daily_research_loss_usd is None or policy.max_daily_research_loss_usd <= 0:
        reasons.append(ResearchKillReason("missing_daily_cap", "max_daily_research_loss_usd is missing or invalid"))
    if policy.max_weekly_research_loss_usd is None or policy.max_weekly_research_loss_usd <= 0:
        reasons.append(ResearchKillReason("missing_weekly_cap", "max_weekly_research_loss_usd is missing or invalid"))
    if policy.max_single_trade_notional_usd is None or policy.max_single_trade_notional_usd <= 0:
        reasons.append(ResearchKillReason("missing_max_notional", "max_single_trade_notional_usd is missing or invalid"))
    if policy.max_research_trades_per_day is None or policy.max_research_trades_per_day <= 0:
        reasons.append(ResearchKillReason("missing_max_trades_per_day", "max_research_trades_per_day is missing or invalid"))

    # 10. Missing allowed symbols
    if not policy.allowed_research_symbols:
        reasons.append(ResearchKillReason("missing_allowed_symbols", "allowed_research_symbols is empty"))
    
    # 11. Missing expiry
    if not policy.research_mode_expires_at:
        reasons.append(ResearchKillReason("missing_expiry", "research_mode_expires_at is missing"))

    # 12. Expired
    if _is_expired(policy.research_mode_expires_at, now):
        reasons.append(ResearchKillReason("expired_approval", f"research mode expired at {policy.research_mode_expires_at}"))

    # 13-17. Missing evidence capture readiness
    journal_list = list(journal_events)
    capture_reasons = live_research_journal_fail_closed_reasons(journal_list)
    for cr in capture_reasons:
        reasons.append(ResearchKillReason(cr, "Journal missing critical capture evidence"))

    # 18. Requested symbol not allowed
    if requested_symbol and policy.allowed_research_symbols and requested_symbol not in policy.allowed_research_symbols:
        reasons.append(ResearchKillReason("symbol_not_allowed", f"Symbol {requested_symbol} not in {policy.allowed_research_symbols}"))

    # 19. Requested notional exceeds single trade max
    if requested_notional and policy.max_single_trade_notional_usd:
        if requested_notional > policy.max_single_trade_notional_usd:
            reasons.append(ResearchKillReason("notional_exceeds_max", f"{requested_notional} > {policy.max_single_trade_notional_usd}"))

    return reasons


def evaluate_research_budget_state(
    policy: ResearchBudgetPolicy,
    journal_events: Iterable[Mapping[str, Any]],
    requested_symbol: str,
    requested_notional: float,
    now: datetime,
) -> ResearchBudgetDecision:
    """Core evaluation logic returning a precise decision based on policy and state."""
    journal_list = list(journal_events)
    
    # 1. Evaluate Fail-Closed Policies
    fail_closed_reasons = research_budget_fail_closed_reasons(
        policy, journal_list, requested_symbol, requested_notional, now
    )
    if fail_closed_reasons:
        return ResearchBudgetDecision(
            decision="FAIL_CLOSED",
            reasons=tuple(fail_closed_reasons)
        )

    # 2. Compute Budget Usage
    state = summarize_research_budget_usage(journal_list, now)
    
    kill_reasons = []

    if state.prior_kill_events > 0:
        kill_reasons.append(ResearchKillReason("prior_kill_event", f"{state.prior_kill_events} prior kill events found in journal"))
    
    if state.total_budget_used_usd >= policy.research_budget_usd:
        kill_reasons.append(ResearchKillReason("total_budget_exceeded", f"Used {state.total_budget_used_usd} >= {policy.research_budget_usd}"))
    
    if state.daily_loss_usd >= policy.max_daily_research_loss_usd:
        kill_reasons.append(ResearchKillReason("daily_loss_exceeded", f"Used {state.daily_loss_usd} >= {policy.max_daily_research_loss_usd}"))
    
    if state.weekly_loss_usd >= policy.max_weekly_research_loss_usd:
        kill_reasons.append(ResearchKillReason("weekly_loss_exceeded", f"Used {state.weekly_loss_usd} >= {policy.max_weekly_research_loss_usd}"))
    
    if state.trades_today >= policy.max_research_trades_per_day:
        kill_reasons.append(ResearchKillReason("max_trades_per_day_exceeded", f"Trades {state.trades_today} >= {policy.max_research_trades_per_day}"))

    if state.broker_error_observations > 0:
        kill_reasons.append(ResearchKillReason("broker_errors_observed", f"{state.broker_error_observations} broker errors in journal"))

    if kill_reasons:
        kill_event = {
            "event_type": "kill_switch_triggered",
            "kill_reason": kill_reasons[0].reason,
            "budget_used_usd": state.total_budget_used_usd,
            "daily_loss_usd": state.daily_loss_usd,
            "weekly_loss_usd": state.weekly_loss_usd,
            "remaining_budget_usd": max(0.0, policy.research_budget_usd - state.total_budget_used_usd),
            "timestamp_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "research_session_id": "budget_monitor",
            "symbol": requested_symbol,
        }
        return ResearchBudgetDecision(
            decision="KILL",
            reasons=tuple(kill_reasons),
            kill_event=kill_event
        )

    return ResearchBudgetDecision(decision="ALLOW", reasons=())


def should_allow_next_research_trade(
    policy: dict,
    journal_path: str | Path,
    requested_symbol: str,
    requested_notional: float,
    now: datetime,
) -> ResearchBudgetDecision:
    """Helper entry point parsing the policy dictionary and loading JSONL."""
    import json
    
    budget_policy = ResearchBudgetPolicy(
        live_research_for_data=policy.get("LIVE_RESEARCH_FOR_DATA", False),
        live_trading_for_profit=policy.get("LIVE_TRADING_FOR_PROFIT", False),
        live_research_approval_present=policy.get("LIVE_RESEARCH_APPROVAL_REQUIRED", False),
        approval_text=policy.get("approval_text", ""),
        research_budget_usd=policy.get("LIVE_RESEARCH_BUDGET_USD", 0.0),
        max_daily_research_loss_usd=policy.get("MAX_DAILY_RESEARCH_LOSS_USD", 0.0),
        max_weekly_research_loss_usd=policy.get("MAX_WEEKLY_RESEARCH_LOSS_USD", 0.0),
        max_single_trade_notional_usd=policy.get("MAX_SINGLE_TRADE_NOTIONAL_USD", 0.0),
        max_research_trades_per_day=policy.get("MAX_RESEARCH_TRADES_PER_DAY", 0),
        allowed_research_symbols=tuple(policy.get("ALLOWED_RESEARCH_SYMBOLS", [])),
        research_mode_expires_at=policy.get("RESEARCH_MODE_EXPIRES_AT", ""),
    )

    events = []
    jp = Path(journal_path)
    if jp.exists() and jp.is_file():
        try:
            with jp.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        except Exception:
            # Add a malformed event so fail_closed triggers correctly
            events.append({"malformed": True})
    
    return evaluate_research_budget_state(budget_policy, events, requested_symbol, requested_notional, now)
