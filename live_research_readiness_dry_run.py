"""P2-042E Live Research Readiness / Dry-Run Wiring.

This module provides an isolated, non-executable dry-run readiness wiring layer
that connects the policy gate, budget monitor, evidence journal structures,
and exploration queue.

It produces readiness decisions and dry-run reports without submitting orders,
mutating files, or calling broker APIs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping, Optional

from live_research_budget import (
    ResearchBudgetPolicy,
    evaluate_research_budget_state,
    summarize_research_budget_usage,
)
from live_research_exploration_queue import (
    ExplorationCandidate,
    ExplorationDecision,
    ExplorationQueue,
    select_next_research_candidate,
)



class LiveResearchReadinessStatus(Enum):
    READY_FOR_APPROVAL_PACKET = "READY_FOR_APPROVAL_PACKET"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    BLOCKED_EVIDENCE_CAPTURE = "BLOCKED_EVIDENCE_CAPTURE"
    BLOCKED_BUDGET = "BLOCKED_BUDGET"
    BLOCKED_NO_CANDIDATE = "BLOCKED_NO_CANDIDATE"
    BLOCKED_LIVE_TRADING_FOR_PROFIT = "BLOCKED_LIVE_TRADING_FOR_PROFIT"
    BLOCKED_RUNTIME_MUTATION = "BLOCKED_RUNTIME_MUTATION"
    BLOCKED_MISSING_APPROVAL = "BLOCKED_MISSING_APPROVAL"


@dataclass(frozen=True)
class LiveResearchReadinessRejectReason:
    reason: str
    context: str


@dataclass(frozen=True)
class LiveResearchReadinessInput:
    # Policy inputs
    live_trading_for_profit: bool
    live_research_enabled: bool

    # Journal/Evidence inputs
    journal_path: str
    requires_journal_validation: bool

    # Budget inputs
    budget_config: ResearchBudgetPolicy
    journal_events_for_budget: tuple[Mapping[str, Any], ...]
    
    # Exploration inputs
    exploration_queue: ExplorationQueue
    allowed_symbols: tuple[str, ...]
    max_spread_bps: float
    max_notional_usd: float

    # Future approval simulation
    simulated_approval_phrase: Optional[str] = None


@dataclass(frozen=True)
class LiveResearchReadinessDecision:
    status: LiveResearchReadinessStatus
    reject_reasons: tuple[LiveResearchReadinessRejectReason, ...]
    candidate: Optional[ExplorationCandidate] = None


@dataclass(frozen=True)
class LiveResearchDryRunReport:
    decision: LiveResearchReadinessDecision
    
    # Invariants for this patch
    live_research_enabled: bool = False
    executable: bool = False
    order_submission_enabled: bool = False
    broker_api_required: bool = False
    runtime_mutation_required: bool = False

    approval_packet_preview: Optional[Mapping[str, Any]] = None


def build_live_research_readiness_input(
    live_trading_for_profit: bool,
    live_research_enabled: bool,
    journal_path: str,
    requires_journal_validation: bool,
    budget_config: ResearchBudgetPolicy,
    journal_events_for_budget: tuple[Mapping[str, Any], ...],
    exploration_queue: ExplorationQueue,
    allowed_symbols: tuple[str, ...],
    max_spread_bps: float,
    max_notional_usd: float,
    simulated_approval_phrase: Optional[str] = None,
) -> LiveResearchReadinessInput:
    """Build readiness input structure deterministically."""
    return LiveResearchReadinessInput(
        live_trading_for_profit=live_trading_for_profit,
        live_research_enabled=live_research_enabled,
        journal_path=journal_path,
        requires_journal_validation=requires_journal_validation,
        budget_config=budget_config,
        journal_events_for_budget=journal_events_for_budget,
        exploration_queue=exploration_queue,
        allowed_symbols=allowed_symbols,
        max_spread_bps=max_spread_bps,
        max_notional_usd=max_notional_usd,
        simulated_approval_phrase=simulated_approval_phrase,
    )


def evaluate_live_research_policy_readiness(
    input_data: LiveResearchReadinessInput
) -> list[LiveResearchReadinessRejectReason]:
    """Evaluate P2-042A constraints."""
    reasons = []
    if input_data.live_trading_for_profit:
        reasons.append(
            LiveResearchReadinessRejectReason(
                "live_profit_trading_enabled",
                "live_trading_for_profit is True, must fail closed."
            )
        )
    return reasons


def evaluate_evidence_capture_readiness(
    input_data: LiveResearchReadinessInput
) -> list[LiveResearchReadinessRejectReason]:
    """Evaluate P2-042B constraints."""
    reasons = []
    if input_data.requires_journal_validation and not input_data.journal_path:
        reasons.append(
            LiveResearchReadinessRejectReason(
                "missing_journal_path",
                "evidence capture requires a valid journal_path"
            )
        )
    return reasons


def evaluate_budget_monitor_readiness(
    input_data: LiveResearchReadinessInput
) -> list[LiveResearchReadinessRejectReason]:
    """Evaluate P2-042C constraints."""
    import datetime
    reasons = []
    budget_decision = evaluate_research_budget_state(
        policy=input_data.budget_config,
        journal_events=list(input_data.journal_events_for_budget),
        requested_symbol="",
        requested_notional=0.0,
        now=datetime.datetime.now(datetime.timezone.utc)
    )

    if budget_decision.decision != "ALLOW":
        reasons.append(
            LiveResearchReadinessRejectReason(
                "budget_monitor_blocked",
                f"Budget monitor decision was {budget_decision.decision}: {budget_decision.reasons}"
            )
        )
    return reasons


def evaluate_exploration_queue_readiness(
    input_data: LiveResearchReadinessInput
) -> ExplorationDecision:
    """Evaluate P2-042D constraints and pick a candidate."""
    return select_next_research_candidate(
        queue=input_data.exploration_queue,
        allowed_symbols=input_data.allowed_symbols,
        max_spread_bps=input_data.max_spread_bps,
        max_notional_usd=input_data.max_notional_usd,
        live_trading_for_profit=input_data.live_trading_for_profit,
    )


def run_live_research_readiness_dry_run(
    input_data: LiveResearchReadinessInput
) -> LiveResearchDryRunReport:
    """Orchestrate all P2-042 component evaluations to generate a dry-run report."""
    
    # 1. Policy Gate
    policy_reasons = evaluate_live_research_policy_readiness(input_data)
    if policy_reasons:
        return LiveResearchDryRunReport(
            decision=LiveResearchReadinessDecision(
                status=LiveResearchReadinessStatus.BLOCKED_LIVE_TRADING_FOR_PROFIT,
                reject_reasons=tuple(policy_reasons)
            )
        )

    # 2. Evidence Capture
    evidence_reasons = evaluate_evidence_capture_readiness(input_data)
    if evidence_reasons:
        return LiveResearchDryRunReport(
            decision=LiveResearchReadinessDecision(
                status=LiveResearchReadinessStatus.BLOCKED_EVIDENCE_CAPTURE,
                reject_reasons=tuple(evidence_reasons)
            )
        )

    # 3. Budget Monitor
    budget_reasons = evaluate_budget_monitor_readiness(input_data)
    if budget_reasons:
        return LiveResearchDryRunReport(
            decision=LiveResearchReadinessDecision(
                status=LiveResearchReadinessStatus.BLOCKED_BUDGET,
                reject_reasons=tuple(budget_reasons)
            )
        )

    # 4. Exploration Queue
    exploration_decision = evaluate_exploration_queue_readiness(input_data)
    if exploration_decision.candidate is None:
        reasons = [
            LiveResearchReadinessRejectReason(r.reason, r.context) 
            for r in exploration_decision.reject_reasons
        ]
        if not reasons:
            reasons = [LiveResearchReadinessRejectReason("no_candidate_in_queue", "Queue is empty")]
            
        return LiveResearchDryRunReport(
            decision=LiveResearchReadinessDecision(
                status=LiveResearchReadinessStatus.BLOCKED_NO_CANDIDATE,
                reject_reasons=tuple(reasons)
            )
        )

    # Simulated approval check (dry run only verifies string shape if present, doesn't actually authorize)
    approval_packet = readiness_report_to_approval_packet_preview(input_data, exploration_decision.candidate)
    
    if input_data.simulated_approval_phrase is None:
        # We are ready for an approval packet, waiting on human
        return LiveResearchDryRunReport(
            decision=LiveResearchReadinessDecision(
                status=LiveResearchReadinessStatus.READY_FOR_APPROVAL_PACKET,
                reject_reasons=(),
                candidate=exploration_decision.candidate
            ),
            approval_packet_preview=approval_packet
        )

    # If they passed an approval phrase for simulation
    valid_shape = f"LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence collection with max loss budget ${input_data.budget_config.research_budget_usd}"
    if input_data.simulated_approval_phrase != valid_shape:
         return LiveResearchDryRunReport(
            decision=LiveResearchReadinessDecision(
                status=LiveResearchReadinessStatus.BLOCKED_MISSING_APPROVAL,
                reject_reasons=(LiveResearchReadinessRejectReason("invalid_approval_phrase", "The provided phrase did not match the expected pattern."),),
                candidate=exploration_decision.candidate
            ),
            approval_packet_preview=approval_packet
        )
    
    # Passed approval phrase shape check during dry-run simulation
    return LiveResearchDryRunReport(
        decision=LiveResearchReadinessDecision(
            status=LiveResearchReadinessStatus.READY_FOR_APPROVAL_PACKET,
            reject_reasons=(),
            candidate=exploration_decision.candidate
        ),
        approval_packet_preview=approval_packet
    )


def readiness_report_to_approval_packet_preview(
    input_data: LiveResearchReadinessInput,
    candidate: ExplorationCandidate
) -> Mapping[str, Any]:
    """Generate the hypothetical approval packet preview dictionary."""
    import datetime
    state = summarize_research_budget_usage(
        events=list(input_data.journal_events_for_budget),
        now=datetime.datetime.now(datetime.timezone.utc)
    )

    return {
        "candidate_profile": candidate.profile.value,
        "candidate_symbol": candidate.symbol,
        "proposed_notional_usd": candidate.proposed_notional_usd,
        "gross_expected_edge_bps": candidate.gross_expected_edge_bps,
        "expected_fee_bps": candidate.expected_fee_bps,
        "spread_bps": candidate.spread_bps,
        "expected_slippage_bps": candidate.expected_slippage_bps,
        "net_expected_edge_bps": candidate.net_expected_edge_bps,
        "budget_remaining_usd": input_data.budget_config.research_budget_usd - state.total_budget_used_usd,
        "max_total_research_budget_usd": input_data.budget_config.research_budget_usd,
        "daily_loss_cap_usd": input_data.budget_config.max_daily_research_loss_usd,
        "weekly_loss_cap_usd": input_data.budget_config.max_weekly_research_loss_usd,
        "allowed_symbols": list(input_data.allowed_symbols),
        "required_evidence_capture_fields": ["proposal_evaluated", "skip_observed", "execution_reported"],
        "explicit_statement_1": "no order will be placed without future approval",
        "explicit_statement_2": "LIVE_TRADING_FOR_PROFIT remains false",
    }


def readiness_report_to_dict(report: LiveResearchDryRunReport) -> dict:
    """Deterministically serialize the report."""
    res = {
        "decision_status": report.decision.status.value,
        "reject_reasons": [{"reason": r.reason, "context": r.context} for r in report.decision.reject_reasons],
        "live_research_enabled": report.live_research_enabled,
        "executable": report.executable,
        "order_submission_enabled": report.order_submission_enabled,
        "broker_api_required": report.broker_api_required,
        "runtime_mutation_required": report.runtime_mutation_required,
    }
    
    if report.decision.candidate:
        res["candidate_id"] = report.decision.candidate.candidate_id
        
    if report.approval_packet_preview:
        res["approval_packet_preview"] = dict(report.approval_packet_preview)
        
    return res
