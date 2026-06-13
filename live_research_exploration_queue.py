"""P2-042D High-Volatility Exploration Strategy Queue.

This module provides deterministic proposal generation and ranking for future live research.
It does not submit orders, touch broker APIs, or modify live strategy parameters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from live_research_journal import build_journal_event


class ExplorationProfile(Enum):
    VOLATILITY_BREAKOUT = "volatility_breakout"
    TREND_CONTINUATION = "trend_continuation"
    REVERSAL_SNAPBACK = "reversal_snapback"
    SPREAD_DISLOCATION_SKIP = "spread_dislocation_skip"


@dataclass(frozen=True)
class ExplorationRejectReason:
    reason: str
    context: str


@dataclass(frozen=True)
class ExplorationCandidate:
    candidate_id: str
    symbol: str
    profile: ExplorationProfile
    proposed_side: str
    proposed_notional_usd: float
    gross_expected_edge_bps: float
    expected_fee_bps: float
    spread_bps: float
    expected_slippage_bps: float
    proposal_only_dry_run: bool
    signal_reason: str
    quote_timestamp_utc: str
    bid_price: float
    ask_price: float
    mid_price: float
    quote_age_ms: int

    @property
    def net_expected_edge_bps(self) -> float:
        return (
            self.gross_expected_edge_bps
            - self.expected_fee_bps
            - self.spread_bps
            - self.expected_slippage_bps
        )


@dataclass(frozen=True)
class ExplorationDecision:
    candidate: Optional[ExplorationCandidate]
    reject_reasons: tuple[ExplorationRejectReason, ...]


@dataclass(frozen=True)
class ExplorationQueue:
    candidates: tuple[ExplorationCandidate, ...]


def build_exploration_candidate(
    symbol: str,
    profile: ExplorationProfile,
    proposed_side: str,
    proposed_notional_usd: float,
    gross_expected_edge_bps: float,
    expected_fee_bps: float,
    spread_bps: float,
    expected_slippage_bps: float,
    proposal_only_dry_run: bool,
    signal_reason: str,
    quote_timestamp_utc: str,
    bid_price: float,
    ask_price: float,
    mid_price: float,
    quote_age_ms: int,
) -> ExplorationCandidate:
    """Build a deterministic exploration candidate without side effects."""
    return ExplorationCandidate(
        candidate_id=f"cand-{uuid.uuid4()}",
        symbol=symbol,
        profile=profile,
        proposed_side=proposed_side,
        proposed_notional_usd=proposed_notional_usd,
        gross_expected_edge_bps=gross_expected_edge_bps,
        expected_fee_bps=expected_fee_bps,
        spread_bps=spread_bps,
        expected_slippage_bps=expected_slippage_bps,
        proposal_only_dry_run=proposal_only_dry_run,
        signal_reason=signal_reason,
        quote_timestamp_utc=quote_timestamp_utc,
        bid_price=bid_price,
        ask_price=ask_price,
        mid_price=mid_price,
        quote_age_ms=quote_age_ms,
    )


def score_exploration_candidate(candidate: ExplorationCandidate) -> float:
    """Calculate the net expected edge of a candidate."""
    return candidate.net_expected_edge_bps


def reject_candidate_reasons(
    candidate: ExplorationCandidate,
    allowed_symbols: tuple[str, ...],
    max_spread_bps: float,
    max_notional_usd: float,
    live_trading_for_profit: bool,
) -> list[ExplorationRejectReason]:
    """Determine if a candidate must be rejected based on constraints."""
    reasons = []

    if live_trading_for_profit:
        reasons.append(ExplorationRejectReason("live_profit_trading_enabled", "live_trading_for_profit must be False"))

    if candidate.net_expected_edge_bps <= 0:
        reasons.append(ExplorationRejectReason("negative_or_zero_net_edge", f"Net edge {candidate.net_expected_edge_bps} <= 0"))

    if candidate.spread_bps > max_spread_bps:
        reasons.append(ExplorationRejectReason("excessive_spread", f"Spread {candidate.spread_bps} > {max_spread_bps}"))

    if candidate.proposed_notional_usd > max_notional_usd:
        reasons.append(ExplorationRejectReason("excessive_notional", f"Notional {candidate.proposed_notional_usd} > {max_notional_usd}"))

    if candidate.symbol not in allowed_symbols:
        reasons.append(ExplorationRejectReason("symbol_not_allowed", f"Symbol {candidate.symbol} not in allowed symbols"))

    return reasons


def rank_exploration_candidates(candidates: Sequence[ExplorationCandidate]) -> list[ExplorationCandidate]:
    """Sort candidates deterministically by highest net expected edge."""
    return sorted(candidates, key=score_exploration_candidate, reverse=True)


def select_next_research_candidate(
    queue: ExplorationQueue,
    allowed_symbols: tuple[str, ...],
    max_spread_bps: float,
    max_notional_usd: float,
    live_trading_for_profit: bool,
) -> ExplorationDecision:
    """Select the highest-edge valid candidate or safely return no candidate."""
    ranked = rank_exploration_candidates(queue.candidates)
    
    all_reject_reasons = []

    for candidate in ranked:
        reasons = reject_candidate_reasons(
            candidate, allowed_symbols, max_spread_bps, max_notional_usd, live_trading_for_profit
        )
        if not reasons:
            return ExplorationDecision(candidate=candidate, reject_reasons=())
        else:
            all_reject_reasons.extend(reasons)

    return ExplorationDecision(candidate=None, reject_reasons=tuple(all_reject_reasons))


def candidate_to_journal_proposal_event(
    candidate: ExplorationCandidate,
    research_session_id: str,
    run_id: str,
    correlation_id: str,
    now_utc: datetime,
) -> Mapping[str, Any]:
    """Convert a valid candidate into a P2-042B-compatible proposal_evaluated event."""
    ts = now_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # Required for P2-042B baseline
    base_values = {
        "research_session_id": research_session_id,
        "run_id": run_id,
        "correlation_id": correlation_id,
        "symbol": candidate.symbol,
        "mode": "live_research_evidence" if not candidate.proposal_only_dry_run else "dry_run",
        "source": "exploration_queue",
        "created_by": "p2_042d_exploration",
        "proposal_side": candidate.proposed_side,
        "proposal_notional_usd": candidate.proposed_notional_usd,
        "proposal_qty": candidate.proposed_notional_usd / candidate.mid_price,
        "signal_reason": f"{candidate.profile.value}: {candidate.signal_reason}",
        "signal_score": candidate.net_expected_edge_bps,
        "decision": "allow_research_intent" if not candidate.proposal_only_dry_run else "dry_run_only",
        "decision_reason": "highest edge valid candidate",
        "expected_move_bps": candidate.gross_expected_edge_bps,
        "expected_fee_bps": candidate.expected_fee_bps,
        "expected_spread_bps": candidate.spread_bps,
        "expected_slippage_bps": candidate.expected_slippage_bps,
        "quote_timestamp_utc": candidate.quote_timestamp_utc,
        "bid_price": candidate.bid_price,
        "ask_price": candidate.ask_price,
        "mid_price": candidate.mid_price,
        "spread_abs": round(candidate.ask_price - candidate.bid_price, 8),
        "spread_bps": candidate.spread_bps,
        "quote_age_ms": candidate.quote_age_ms,
        "replay_dataset_id": "none",
        "replay_window_start_utc": candidate.quote_timestamp_utc,
        "replay_window_end_utc": candidate.quote_timestamp_utc,
        "replay_signal_match": False,
        "replay_expected_decision": "none",
        "live_decision": "buy" if candidate.proposed_side == "buy" else "sell",
        "divergence_reason": "none",
    }

    return build_journal_event("proposal_evaluated", timestamp_utc=ts, values=base_values)


def rejected_candidate_to_skip_journal_event(
    candidate: ExplorationCandidate,
    reasons: Sequence[ExplorationRejectReason],
    research_session_id: str,
    run_id: str,
    correlation_id: str,
    now_utc: datetime,
) -> Mapping[str, Any]:
    """Convert a rejected candidate into a P2-042B-compatible skip_observed event."""
    ts = now_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    
    reason_strs = [r.reason for r in reasons]
    combined_reason = ",".join(reason_strs)

    base_values = {
        "research_session_id": research_session_id,
        "run_id": run_id,
        "correlation_id": correlation_id,
        "symbol": candidate.symbol,
        "mode": "live_research_evidence" if not candidate.proposal_only_dry_run else "dry_run",
        "source": "exploration_queue",
        "created_by": "p2_042d_exploration",
        "decision": "skip",
        "decision_reason": "candidate rejected by constraints",
        "skip_reason": combined_reason,
        "replay_dataset_id": "none",
        "replay_window_start_utc": candidate.quote_timestamp_utc,
        "replay_window_end_utc": candidate.quote_timestamp_utc,
        "replay_signal_match": False,
        "replay_expected_decision": "none",
        "live_decision": "skip",
        "divergence_reason": "none",
    }

    return build_journal_event("skip_observed", timestamp_utc=ts, values=base_values)
