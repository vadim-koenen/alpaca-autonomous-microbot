"""
P2-043A Profit Thesis / EV Contract

A pure, deterministic profitability contract layer ensuring every trade
has mathematically positive expected value after all costs.
"""

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple


class ProfitThesisStatus(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProfitThesisRejectReason(Enum):
    NEGATIVE_NET_EDGE = "NEGATIVE_NET_EDGE"
    INSUFFICIENT_NET_EDGE = "INSUFFICIENT_NET_EDGE"
    MOVE_BELOW_COST = "MOVE_BELOW_COST"
    MISSING_HOLD_MINUTES = "MISSING_HOLD_MINUTES"
    INVALID_HOLD_MINUTES = "INVALID_HOLD_MINUTES"
    MISSING_INVALIDATION = "MISSING_INVALIDATION"
    MISSING_TARGET = "MISSING_TARGET"
    MISSING_EVIDENCE_REQUIREMENTS = "MISSING_EVIDENCE_REQUIREMENTS"
    LIVE_TRADING_FOR_PROFIT_NOT_ALLOWED = "LIVE_TRADING_FOR_PROFIT_NOT_ALLOWED"
    MISSING_NARRATIVE = "MISSING_NARRATIVE"
    INCOMPLETE_COST_MODEL = "INCOMPLETE_COST_MODEL"
    MISSING_FEE_ASSUMPTIONS = "MISSING_FEE_ASSUMPTIONS"


@dataclass(frozen=True)
class TradeEconomicInputs:
    why_this_symbol: Optional[str]
    why_now: Optional[str]
    signal_name: Optional[str]
    signal_value: Optional[float]


@dataclass(frozen=True)
class TradeCostModel:
    expected_fee_bps: Optional[float]
    expected_spread_bps: Optional[float]
    expected_slippage_bps: Optional[float]


@dataclass(frozen=True)
class ExpectedMoveModel:
    expected_move_bps: Optional[float]
    expected_hold_minutes: Optional[int]
    invalidation_price_or_bps: Optional[float]
    target_price_or_bps: Optional[float]
    max_loss_usd: Optional[float]
    evidence_required_after_trade: Optional[str]
    scale_no_scale_criteria: Optional[str]


@dataclass(frozen=True)
class ProfitThesis:
    inputs: TradeEconomicInputs
    costs: TradeCostModel
    move: ExpectedMoveModel
    round_trip_cost_bps: float
    gross_expected_edge_bps: float
    net_expected_edge_bps: float
    minimum_required_edge_bps: float


@dataclass(frozen=True)
class ProfitThesisDecision:
    status: ProfitThesisStatus
    reject_reasons: Tuple[ProfitThesisRejectReason, ...]
    thesis: Optional[ProfitThesis]


def calculate_round_trip_cost_bps(costs: TradeCostModel) -> float:
    fee = costs.expected_fee_bps or 0.0
    spread = costs.expected_spread_bps or 0.0
    slippage = costs.expected_slippage_bps or 0.0
    return fee + spread + slippage


def calculate_expected_net_edge_bps(gross_edge_bps: float, costs: TradeCostModel) -> float:
    fee = costs.expected_fee_bps or 0.0
    spread = costs.expected_spread_bps or 0.0
    slippage = costs.expected_slippage_bps or 0.0
    return gross_edge_bps - fee - spread - slippage


def build_profit_thesis(
    inputs: TradeEconomicInputs,
    costs: TradeCostModel,
    move: ExpectedMoveModel,
    gross_expected_edge_bps: float,
) -> ProfitThesis:
    round_trip_cost_bps = calculate_round_trip_cost_bps(costs)
    net_expected_edge_bps = calculate_expected_net_edge_bps(gross_expected_edge_bps, costs)
    minimum_required_edge_bps = 2.0 * round_trip_cost_bps
    
    return ProfitThesis(
        inputs=inputs,
        costs=costs,
        move=move,
        round_trip_cost_bps=round_trip_cost_bps,
        gross_expected_edge_bps=gross_expected_edge_bps,
        net_expected_edge_bps=net_expected_edge_bps,
        minimum_required_edge_bps=minimum_required_edge_bps,
    )


def evaluate_profit_thesis(
    thesis: ProfitThesis,
    live_trading_for_profit: bool,
) -> ProfitThesisDecision:
    reasons: List[ProfitThesisRejectReason] = []
    
    if live_trading_for_profit:
        reasons.append(ProfitThesisRejectReason.LIVE_TRADING_FOR_PROFIT_NOT_ALLOWED)
        
    if not thesis.inputs.why_this_symbol or not thesis.inputs.why_this_symbol.strip():
        reasons.append(ProfitThesisRejectReason.MISSING_NARRATIVE)
    elif not thesis.inputs.why_now or not thesis.inputs.why_now.strip():
        reasons.append(ProfitThesisRejectReason.MISSING_NARRATIVE)
        
    if thesis.costs.expected_fee_bps is None:
        reasons.append(ProfitThesisRejectReason.MISSING_FEE_ASSUMPTIONS)
    elif thesis.costs.expected_spread_bps is None or thesis.costs.expected_slippage_bps is None:
        reasons.append(ProfitThesisRejectReason.INCOMPLETE_COST_MODEL)
        
    if thesis.move.expected_hold_minutes is None:
        reasons.append(ProfitThesisRejectReason.MISSING_HOLD_MINUTES)
    elif thesis.move.expected_hold_minutes <= 0:
        reasons.append(ProfitThesisRejectReason.INVALID_HOLD_MINUTES)
        
    if thesis.move.invalidation_price_or_bps is None:
        reasons.append(ProfitThesisRejectReason.MISSING_INVALIDATION)
        
    if thesis.move.target_price_or_bps is None:
        reasons.append(ProfitThesisRejectReason.MISSING_TARGET)
        
    if not thesis.move.evidence_required_after_trade or not thesis.move.evidence_required_after_trade.strip():
        reasons.append(ProfitThesisRejectReason.MISSING_EVIDENCE_REQUIREMENTS)
        
    if thesis.move.expected_move_bps is None or thesis.move.expected_move_bps <= thesis.round_trip_cost_bps:
        reasons.append(ProfitThesisRejectReason.MOVE_BELOW_COST)
        
    if thesis.net_expected_edge_bps <= 0:
        reasons.append(ProfitThesisRejectReason.NEGATIVE_NET_EDGE)
        
    if thesis.net_expected_edge_bps < thesis.minimum_required_edge_bps:
        reasons.append(ProfitThesisRejectReason.INSUFFICIENT_NET_EDGE)
        
    if reasons:
        return ProfitThesisDecision(
            status=ProfitThesisStatus.REJECTED,
            reject_reasons=tuple(reasons),
            thesis=thesis,
        )
        
    return ProfitThesisDecision(
        status=ProfitThesisStatus.APPROVED,
        reject_reasons=(),
        thesis=thesis,
    )


def profit_thesis_to_dict(decision: ProfitThesisDecision) -> Dict[str, Any]:
    """Serialize the decision and thesis for general dict usage."""
    out = {
        "status": decision.status.value,
        "reject_reasons": [r.value for r in decision.reject_reasons],
    }
    if decision.thesis:
        out.update({
            "why_this_symbol": decision.thesis.inputs.why_this_symbol,
            "why_now": decision.thesis.inputs.why_now,
            "signal_name": decision.thesis.inputs.signal_name,
            "signal_value": decision.thesis.inputs.signal_value,
            "expected_fee_bps": decision.thesis.costs.expected_fee_bps,
            "expected_spread_bps": decision.thesis.costs.expected_spread_bps,
            "expected_slippage_bps": decision.thesis.costs.expected_slippage_bps,
            "expected_move_bps": decision.thesis.move.expected_move_bps,
            "expected_hold_minutes": decision.thesis.move.expected_hold_minutes,
            "invalidation_price_or_bps": decision.thesis.move.invalidation_price_or_bps,
            "target_price_or_bps": decision.thesis.move.target_price_or_bps,
            "max_loss_usd": decision.thesis.move.max_loss_usd,
            "evidence_required_after_trade": decision.thesis.move.evidence_required_after_trade,
            "scale_no_scale_criteria": decision.thesis.move.scale_no_scale_criteria,
            "round_trip_cost_bps": decision.thesis.round_trip_cost_bps,
            "gross_expected_edge_bps": decision.thesis.gross_expected_edge_bps,
            "net_expected_edge_bps": decision.thesis.net_expected_edge_bps,
            "minimum_required_edge_bps": decision.thesis.minimum_required_edge_bps,
        })
    return out


def profit_thesis_to_journal_fields(decision: ProfitThesisDecision) -> Dict[str, Any]:
    """Subset for flat journal fields required by the live_research_journal."""
    d = profit_thesis_to_dict(decision)
    # The journal likely needs prefixes to avoid collision if mixed with other events,
    # or just a clean extraction. We will return exactly what the EV contract specifies.
    return {f"thesis_{k}": v for k, v in d.items()}
