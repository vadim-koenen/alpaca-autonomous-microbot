"""Classify proposed changes by operational risk.

The classifier is advisory only. No class enables auto-deploy in this patch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangeRisk:
    risk_class: int
    label: str
    requires_human_approval: bool
    separate_risk_review_required: bool
    auto_deploy_enabled: bool
    reason: str


CLASS_LABELS = {
    0: "safe_auto_candidate",
    1: "low_risk_operational",
    2: "trading_safety",
    3: "strategy_or_risk_expansion",
}


CLASS_3_TERMS = {
    "new strategy",
    "new strategies",
    "new symbol",
    "new symbols",
    "larger sizing",
    "higher exposure",
    "higher exposure cap",
    "increase exposure",
    "increase notional",
    "margin",
    "shorting",
    "options",
    "leverage",
    "staking",
    "stake",
    "lockup",
    "lockups",
    "automated transfer",
    "auto-transfer",
    "transfer automation",
}

CLASS_2_PATH_PARTS = {
    "risk_manager.py",
    "order_manager.py",
    "position_manager.py",
    "broker_alpaca.py",
    "broker_coinbase.py",
}

CLASS_2_TERMS = {
    "risk_manager",
    "order_manager",
    "position_manager",
    "broker adapter",
    "broker adapters",
    "exposure calculation",
    "aggregate exposure",
    "stop loss",
    "stop-loss",
    "take profit",
    "take-profit",
}

CLASS_1_PATH_PARTS = {
    "scripts/status.sh",
    "scripts/reconcile.sh",
    "memory/",
    "heartbeat",
}

CLASS_1_TERMS = {
    "logging",
    "reconciliation output",
    "memory write",
    "memory writes",
    "heartbeat",
    "secret-safe diagnostic",
    "secret-safe diagnostics",
}

CLASS_0_PATH_PREFIXES = ("docs/", "tests/")
CLASS_0_TERMS = {
    "docs",
    "documentation",
    "comments",
    "tests",
    "read-only diagnostic",
    "read-only diagnostics",
    "summary formatting",
}


def classify_change(path: str = "", change_type: str = "", summary: str = "") -> ChangeRisk:
    """Return the highest applicable risk class for a proposed change."""
    normalized_path = _normalize_path(path)
    text = f"{normalized_path} {change_type} {summary}".lower()

    if normalized_path.startswith(CLASS_0_PATH_PREFIXES):
        return _risk(0, "docs/tests path matched")

    if _contains_any(text, CLASS_3_TERMS):
        return _risk(3, "strategy/risk expansion term matched")

    if (
        any(part in normalized_path for part in CLASS_2_PATH_PARTS)
        or _contains_any(text, CLASS_2_TERMS)
    ):
        return _risk(2, "trading safety path or term matched")

    if (
        any(part in normalized_path for part in CLASS_1_PATH_PARTS)
        or _contains_any(text, CLASS_1_TERMS)
    ):
        return _risk(1, "operational observability path or term matched")

    if _contains_any(text, CLASS_0_TERMS):
        return _risk(0, "docs/tests/read-only path or term matched")

    return _risk(1, "default conservative operational classification")


def _normalize_path(path: str) -> str:
    return Path(path).as_posix().lstrip("./").lower()


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _risk(risk_class: int, reason: str) -> ChangeRisk:
    return ChangeRisk(
        risk_class=risk_class,
        label=CLASS_LABELS[risk_class],
        requires_human_approval=risk_class >= 2,
        separate_risk_review_required=risk_class >= 3,
        auto_deploy_enabled=False,
        reason=reason,
    )
