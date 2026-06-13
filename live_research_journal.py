"""P2-042B isolated live-research evidence journal helpers.

The module is intentionally disconnected from live execution. It does not read
environment variables, import broker/order/runtime modules, or choose a default
journal path. Callers must supply an explicit JSONL path.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence


LIVE_RESEARCH_JOURNAL_SCHEMA_VERSION = "p2_042b_v1"

RESEARCH_EVENT_TYPES = (
    "research_session_started",
    "proposal_evaluated",
    "trade_intent_created",
    "order_submitted_observed",
    "fill_observed",
    "position_mark_observed",
    "exit_observed",
    "skip_observed",
    "kill_switch_triggered",
    "research_session_closed",
)

TOP_LEVEL_FIELDS = (
    "schema_version",
    "event_id",
    "event_type",
    "timestamp_utc",
    "research_session_id",
    "run_id",
    "correlation_id",
    "symbol",
    "mode",
    "live_research_for_data",
    "live_trading_for_profit",
    "strategy_id",
    "signal_id",
    "decision_id",
    "source",
    "created_by",
)

POLICY_LINKAGE_FIELDS = (
    "live_research_policy_version",
    "live_research_approval_present",
    "live_research_budget_usd",
    "max_daily_research_loss_usd",
    "max_weekly_research_loss_usd",
    "max_single_trade_notional_usd",
    "max_research_trades_per_day",
    "research_mode_expires_at",
)

PROPOSAL_DECISION_FIELDS = (
    "proposal_side",
    "proposal_notional_usd",
    "proposal_qty",
    "signal_reason",
    "signal_score",
    "decision",
    "decision_reason",
    "skip_reason",
    "expected_move_bps",
    "expected_fee_bps",
    "expected_spread_bps",
    "expected_slippage_bps",
)

QUOTE_FIELDS = (
    "quote_timestamp_utc",
    "bid_price",
    "ask_price",
    "mid_price",
    "spread_abs",
    "spread_bps",
    "quote_age_ms",
)

ORDER_FIELDS = (
    "client_order_id",
    "broker_order_id",
    "order_type",
    "time_in_force",
    "post_only",
    "requested_side",
    "requested_qty",
    "requested_notional_usd",
    "requested_limit_price",
    "submitted_at_utc",
    "observed_order_status",
)

FILL_FIELDS = (
    "fill_id",
    "fill_timestamp_utc",
    "fill_side",
    "fill_qty",
    "avg_fill_price",
    "gross_notional_usd",
    "fee_amount",
    "fee_currency",
    "fee_bps",
    "liquidity_flag",
    "fill_source",
    "fill_complete",
)

SLIPPAGE_FIELDS = (
    "reference_mid_price",
    "reference_bid_price",
    "reference_ask_price",
    "slippage_abs",
    "slippage_bps",
    "effective_spread_bps",
)

MFE_MAE_FIELDS = (
    "entry_price",
    "current_mark_price",
    "best_price_since_entry",
    "worst_price_since_entry",
    "mfe_abs",
    "mfe_bps",
    "mae_abs",
    "mae_bps",
    "mfe_timestamp_utc",
    "mae_timestamp_utc",
)

EXIT_PNL_FIELDS = (
    "exit_reason",
    "exit_timestamp_utc",
    "exit_price",
    "realized_gross_pnl_usd",
    "realized_fees_usd",
    "realized_slippage_usd",
    "realized_net_pnl_usd",
    "hold_seconds",
)

REPLAY_LINKAGE_FIELDS = (
    "replay_dataset_id",
    "replay_window_start_utc",
    "replay_window_end_utc",
    "replay_signal_match",
    "replay_expected_decision",
    "live_decision",
    "divergence_reason",
)

JOURNAL_FIELDS = tuple(
    dict.fromkeys(
        TOP_LEVEL_FIELDS
        + POLICY_LINKAGE_FIELDS
        + PROPOSAL_DECISION_FIELDS
        + QUOTE_FIELDS
        + ORDER_FIELDS
        + FILL_FIELDS
        + SLIPPAGE_FIELDS
        + MFE_MAE_FIELDS
        + EXIT_PNL_FIELDS
        + REPLAY_LINKAGE_FIELDS
    )
)

CORE_VALUE_FIELDS = (
    "schema_version",
    "event_id",
    "event_type",
    "timestamp_utc",
    "research_session_id",
    "run_id",
    "correlation_id",
    "symbol",
    "mode",
    "source",
    "created_by",
)

RESEARCH_POLICY_VALUE_FIELDS = (
    "live_research_policy_version",
    "live_research_budget_usd",
    "max_daily_research_loss_usd",
    "max_weekly_research_loss_usd",
    "max_single_trade_notional_usd",
    "max_research_trades_per_day",
    "research_mode_expires_at",
)

PROPOSAL_REQUIRED_FIELDS = (
    "proposal_side",
    "signal_reason",
    "signal_score",
    "decision",
    "decision_reason",
    "expected_move_bps",
    "expected_fee_bps",
    "expected_spread_bps",
    "expected_slippage_bps",
)

TRADE_INTENT_REQUIRED_FIELDS = (
    "proposal_side",
    "decision",
    "decision_reason",
    "client_order_id",
    "order_type",
    "time_in_force",
    "post_only",
    "requested_side",
    "requested_qty",
    "requested_notional_usd",
    "requested_limit_price",
)

ORDER_OBSERVATION_REQUIRED_FIELDS = ORDER_FIELDS

EVENT_REQUIRED_FIELDS = {
    "research_session_started": (),
    "proposal_evaluated": PROPOSAL_REQUIRED_FIELDS + QUOTE_FIELDS + REPLAY_LINKAGE_FIELDS,
    "trade_intent_created": TRADE_INTENT_REQUIRED_FIELDS + QUOTE_FIELDS + REPLAY_LINKAGE_FIELDS,
    "order_submitted_observed": ORDER_OBSERVATION_REQUIRED_FIELDS,
    "fill_observed": FILL_FIELDS + SLIPPAGE_FIELDS + REPLAY_LINKAGE_FIELDS,
    "position_mark_observed": MFE_MAE_FIELDS,
    "exit_observed": EXIT_PNL_FIELDS + REPLAY_LINKAGE_FIELDS,
    "skip_observed": (
        "decision",
        "decision_reason",
        "skip_reason",
    )
    + REPLAY_LINKAGE_FIELDS,
    "kill_switch_triggered": ("decision", "decision_reason"),
    "research_session_closed": ("decision", "decision_reason"),
}

BOOLEAN_FIELDS = {
    "live_research_for_data",
    "live_trading_for_profit",
    "live_research_approval_present",
    "post_only",
    "fill_complete",
    "replay_signal_match",
}

NUMERIC_FIELDS = {
    "live_research_budget_usd",
    "max_daily_research_loss_usd",
    "max_weekly_research_loss_usd",
    "max_single_trade_notional_usd",
    "max_research_trades_per_day",
    "proposal_notional_usd",
    "proposal_qty",
    "signal_score",
    "expected_move_bps",
    "expected_fee_bps",
    "expected_spread_bps",
    "expected_slippage_bps",
    "bid_price",
    "ask_price",
    "mid_price",
    "spread_abs",
    "spread_bps",
    "quote_age_ms",
    "requested_qty",
    "requested_notional_usd",
    "requested_limit_price",
    "fill_qty",
    "avg_fill_price",
    "gross_notional_usd",
    "fee_amount",
    "fee_bps",
    "reference_mid_price",
    "reference_bid_price",
    "reference_ask_price",
    "slippage_abs",
    "slippage_bps",
    "effective_spread_bps",
    "entry_price",
    "current_mark_price",
    "best_price_since_entry",
    "worst_price_since_entry",
    "mfe_abs",
    "mfe_bps",
    "mae_abs",
    "mae_bps",
    "exit_price",
    "realized_gross_pnl_usd",
    "realized_fees_usd",
    "realized_slippage_usd",
    "realized_net_pnl_usd",
    "hold_seconds",
}

POSITIVE_FIELDS = {
    "live_research_budget_usd",
    "max_daily_research_loss_usd",
    "max_weekly_research_loss_usd",
    "max_single_trade_notional_usd",
    "max_research_trades_per_day",
    "proposal_notional_usd",
    "proposal_qty",
    "bid_price",
    "ask_price",
    "mid_price",
    "spread_abs",
    "requested_qty",
    "requested_notional_usd",
    "requested_limit_price",
    "fill_qty",
    "avg_fill_price",
    "gross_notional_usd",
    "reference_mid_price",
    "reference_bid_price",
    "reference_ask_price",
    "entry_price",
    "current_mark_price",
    "best_price_since_entry",
    "worst_price_since_entry",
    "exit_price",
}

NONNEGATIVE_FIELDS = {
    "fee_amount",
    "fee_bps",
    "quote_age_ms",
    "mfe_abs",
    "mfe_bps",
    "mae_abs",
    "mae_bps",
    "realized_fees_usd",
    "hold_seconds",
}

TIMESTAMP_FIELDS = {
    "timestamp_utc",
    "research_mode_expires_at",
    "quote_timestamp_utc",
    "submitted_at_utc",
    "fill_timestamp_utc",
    "mfe_timestamp_utc",
    "mae_timestamp_utc",
    "exit_timestamp_utc",
    "replay_window_start_utc",
    "replay_window_end_utc",
}

SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|token|password|private[_-]?key|credential|"
    r"authorization|bearer|cb[_-]?access|signature)",
    re.IGNORECASE,
)
ACCOUNT_KEY_RE = re.compile(
    r"(account[_-]?(?:id|uuid|number|num)|portfolio[_-]?id|wallet[_-]?id)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|private[_-]?key|authorization|"
    r"bearer|cb[_-]?access|account[_-]?id)\s*[:=]\s*\S+"
)


def utc_now_iso(now: Optional[datetime] = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _valid_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0


def _privacy_reasons(value: Any, key: str = "") -> list[str]:
    reasons: list[str] = []
    key_text = str(key)
    if SECRET_KEY_RE.search(key_text):
        reasons.append(f"secret_field_forbidden:{key_text}")
    if ACCOUNT_KEY_RE.search(key_text):
        reasons.append(f"account_identifier_field_forbidden:{key_text}")
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            reasons.extend(_privacy_reasons(child_value, str(child_key)))
    elif isinstance(value, (list, tuple)):
        for item in value:
            reasons.extend(_privacy_reasons(item, key_text))
    elif isinstance(value, str) and SECRET_VALUE_RE.search(value):
        reasons.append(f"sensitive_value_forbidden:{key_text or 'value'}")
    return reasons


def build_journal_event(
    event_type: str,
    *,
    event_id: Optional[str] = None,
    timestamp_utc: Optional[str] = None,
    values: Optional[Mapping[str, Any]] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a deterministic schema-shaped event without writing it."""
    supplied = dict(values or {})
    supplied.update(overrides)
    unknown = sorted(set(supplied) - set(JOURNAL_FIELDS))
    if unknown:
        raise ValueError(f"unknown journal fields: {unknown}")

    event = {field: None for field in JOURNAL_FIELDS}
    event.update(
        {
            "schema_version": LIVE_RESEARCH_JOURNAL_SCHEMA_VERSION,
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp_utc": timestamp_utc or utc_now_iso(),
            "live_research_for_data": False,
            "live_trading_for_profit": False,
        }
    )
    event.update(supplied)
    return event


def validate_journal_event(event: Any) -> list[str]:
    """Return explicit fail-closed reasons; an empty list means valid."""
    if not isinstance(event, Mapping):
        return ["event_must_be_mapping"]

    reasons = _privacy_reasons(event)
    actual = set(event)
    expected = set(JOURNAL_FIELDS)
    for field in sorted(expected - actual):
        reasons.append(f"missing_schema_field:{field}")
    for field in sorted(actual - expected):
        reasons.append(f"unexpected_schema_field:{field}")
    if expected - actual:
        return list(dict.fromkeys(reasons))

    for field in CORE_VALUE_FIELDS:
        if not _present(event.get(field)):
            reasons.append(f"missing_required_field:{field}")

    event_type = event.get("event_type")
    if event_type not in RESEARCH_EVENT_TYPES:
        reasons.append("invalid_event_type")
    if event.get("schema_version") != LIVE_RESEARCH_JOURNAL_SCHEMA_VERSION:
        reasons.append("invalid_schema_version")

    for field in ("live_research_for_data", "live_trading_for_profit"):
        if not isinstance(event.get(field), bool):
            reasons.append(f"invalid_boolean_field:{field}")
    if event.get("live_trading_for_profit") is not False:
        reasons.append("live_trading_for_profit_must_be_false")

    if event.get("live_research_for_data") is True:
        if event.get("live_research_approval_present") is not True:
            reasons.append("live_research_approval_missing")
        for field in RESEARCH_POLICY_VALUE_FIELDS:
            if not _present(event.get(field)):
                reasons.append(f"missing_policy_linkage:{field}")

    required_for_event = EVENT_REQUIRED_FIELDS.get(str(event_type), ())
    for field in required_for_event:
        if not _present(event.get(field)):
            reasons.append(f"missing_event_field:{field}")

    if event_type in {"proposal_evaluated", "trade_intent_created"}:
        if not _present(event.get("proposal_notional_usd")) and not _present(
            event.get("proposal_qty")
        ):
            reasons.append("missing_event_field:proposal_notional_usd_or_proposal_qty")

    for field in BOOLEAN_FIELDS:
        value = event.get(field)
        if value is not None and not isinstance(value, bool):
            reasons.append(f"invalid_boolean_field:{field}")

    for field in NUMERIC_FIELDS:
        value = event.get(field)
        if value is None:
            continue
        parsed = _number(value)
        if parsed is None:
            reasons.append(f"invalid_numeric_field:{field}")
            continue
        if field in POSITIVE_FIELDS and parsed <= 0:
            reasons.append(f"nonpositive_numeric_field:{field}")
        if field in NONNEGATIVE_FIELDS and parsed < 0:
            reasons.append(f"negative_numeric_field:{field}")

    if _present(event.get("max_research_trades_per_day")):
        parsed_trades = _number(event.get("max_research_trades_per_day"))
        if parsed_trades is None or not parsed_trades.is_integer():
            reasons.append("invalid_integer_field:max_research_trades_per_day")

    for field in TIMESTAMP_FIELDS:
        value = event.get(field)
        if value is not None and not _valid_utc_timestamp(value):
            reasons.append(f"invalid_utc_timestamp:{field}")

    for field, choices in {
        "proposal_side": {"buy", "sell"},
        "requested_side": {"buy", "sell"},
        "fill_side": {"buy", "sell"},
    }.items():
        value = event.get(field)
        if value is not None and str(value).lower() not in choices:
            reasons.append(f"invalid_side:{field}")

    if event_type == "fill_observed" and event.get("fill_complete") is not True:
        reasons.append("fill_observed_requires_fill_complete")

    for field, value in event.items():
        if isinstance(value, (Mapping, list, tuple, set)):
            reasons.append(f"nested_value_forbidden:{field}")

    try:
        json.dumps(dict(event), sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        reasons.append("event_not_json_serializable")

    return list(dict.fromkeys(reasons))


def append_journal_event(event: Mapping[str, Any], path: str | Path) -> Path:
    """Validate and append one deterministic JSON object to an explicit path."""
    if path is None or not str(path).strip():
        raise ValueError("explicit JSONL path is required")
    output_path = Path(path)
    if output_path.suffix.lower() != ".jsonl":
        raise ValueError("journal path must end with .jsonl")

    reasons = validate_journal_event(event)
    if reasons:
        raise ValueError("invalid journal event: " + "; ".join(reasons))

    if output_path.exists():
        if not output_path.is_file():
            raise ValueError(f"journal path is not a file: {output_path}")
        if output_path.stat().st_size:
            with output_path.open("rb") as handle:
                handle.seek(-1, 2)
                if handle.read(1) != b"\n":
                    raise ValueError("existing journal is not newline terminated")

    encoded = json.dumps(
        dict(event),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded + "\n")
    return output_path


def compute_spread_bps(bid_price: Any, ask_price: Any, mid_price: Any = None) -> float:
    bid = _number(bid_price)
    ask = _number(ask_price)
    mid = _number(mid_price) if mid_price is not None else None
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        raise ValueError("bid and ask must be positive with ask greater than bid")
    reference_mid = mid if mid is not None else (bid + ask) / 2.0
    if reference_mid <= 0:
        raise ValueError("mid price must be positive")
    return ((ask - bid) / reference_mid) * 10000.0


def compute_slippage_bps(side: str, reference_price: Any, fill_price: Any) -> float:
    """Return signed adverse slippage: positive is worse, negative is better."""
    reference = _number(reference_price)
    fill = _number(fill_price)
    normalized_side = str(side or "").strip().lower()
    if reference is None or fill is None or reference <= 0 or fill <= 0:
        raise ValueError("reference and fill prices must be positive")
    if normalized_side == "buy":
        return ((fill - reference) / reference) * 10000.0
    if normalized_side == "sell":
        return ((reference - fill) / reference) * 10000.0
    raise ValueError("side must be buy or sell")


def update_mfe_mae(
    *,
    side: str,
    entry_price: Any,
    current_mark_price: Any,
    best_price_since_entry: Any = None,
    worst_price_since_entry: Any = None,
    mark_timestamp_utc: Optional[str] = None,
    mfe_timestamp_utc: Optional[str] = None,
    mae_timestamp_utc: Optional[str] = None,
) -> dict[str, Any]:
    """Update favorable/adverse price extremes for a long or short position."""
    normalized_side = str(side or "").strip().lower()
    entry = _number(entry_price)
    mark = _number(current_mark_price)
    previous_best = _number(best_price_since_entry)
    previous_worst = _number(worst_price_since_entry)
    if entry is None or mark is None or entry <= 0 or mark <= 0:
        raise ValueError("entry and current mark prices must be positive")
    if normalized_side not in {"long", "short", "buy", "sell"}:
        raise ValueError("side must be long, short, buy, or sell")
    if mark_timestamp_utc is not None and not _valid_utc_timestamp(mark_timestamp_utc):
        raise ValueError("mark timestamp must be timezone-aware UTC")

    is_long = normalized_side in {"long", "buy"}
    old_best = previous_best if previous_best is not None else entry
    old_worst = previous_worst if previous_worst is not None else entry

    if is_long:
        best = max(old_best, mark)
        worst = min(old_worst, mark)
        mfe_abs = max(best - entry, 0.0)
        mae_abs = max(entry - worst, 0.0)
        new_best = mark > old_best
        new_worst = mark < old_worst
    else:
        best = min(old_best, mark)
        worst = max(old_worst, mark)
        mfe_abs = max(entry - best, 0.0)
        mae_abs = max(worst - entry, 0.0)
        new_best = mark < old_best
        new_worst = mark > old_worst

    return {
        "entry_price": entry,
        "current_mark_price": mark,
        "best_price_since_entry": best,
        "worst_price_since_entry": worst,
        "mfe_abs": mfe_abs,
        "mfe_bps": (mfe_abs / entry) * 10000.0,
        "mae_abs": mae_abs,
        "mae_bps": (mae_abs / entry) * 10000.0,
        "mfe_timestamp_utc": mark_timestamp_utc if new_best else mfe_timestamp_utc,
        "mae_timestamp_utc": mark_timestamp_utc if new_worst else mae_timestamp_utc,
    }


def _capture_complete(event: Mapping[str, Any], fields: Sequence[str]) -> bool:
    return all(_present(event.get(field)) for field in fields)


def detect_missing_fill_capture(events: Iterable[Mapping[str, Any]]) -> bool:
    return not any(
        event.get("event_type") == "fill_observed"
        and _capture_complete(event, FILL_FIELDS)
        and event.get("fill_complete") is True
        for event in events
    )


def detect_missing_fee_capture(events: Iterable[Mapping[str, Any]]) -> bool:
    return not any(
        event.get("event_type") == "fill_observed"
        and _capture_complete(event, ("fee_amount", "fee_currency", "fee_bps"))
        for event in events
    )


def detect_missing_mfe_mae_capture(events: Iterable[Mapping[str, Any]]) -> bool:
    return not any(
        event.get("event_type") == "position_mark_observed"
        and _capture_complete(event, MFE_MAE_FIELDS)
        for event in events
    )


def live_research_journal_fail_closed_reasons(
    events: Optional[Iterable[Mapping[str, Any]]],
) -> list[str]:
    event_list = list(events or [])
    reasons: list[str] = []
    if not event_list:
        return [
            "missing_journal_capture",
            "missing_fill_capture",
            "missing_fee_capture",
            "missing_mfe_mae_capture",
        ]

    for index, event in enumerate(event_list):
        validation_reasons = validate_journal_event(event)
        if validation_reasons:
            reasons.append(f"invalid_journal_event:{index}")

    if detect_missing_fill_capture(event_list):
        reasons.append("missing_fill_capture")
    if detect_missing_fee_capture(event_list):
        reasons.append("missing_fee_capture")
    if detect_missing_mfe_mae_capture(event_list):
        reasons.append("missing_mfe_mae_capture")
    return list(dict.fromkeys(reasons))


def live_research_journal_capture_ready(
    events: Optional[Iterable[Mapping[str, Any]]],
) -> bool:
    return not live_research_journal_fail_closed_reasons(events)


def live_research_journal_readiness(
    events: Optional[Iterable[Mapping[str, Any]]],
) -> dict[str, Any]:
    event_list = list(events or [])
    reasons = live_research_journal_fail_closed_reasons(event_list)
    return {
        "ready": not reasons,
        "fail_closed_reasons": reasons,
        "journal_capture_present": bool(event_list),
        "fill_capture_present": not detect_missing_fill_capture(event_list),
        "fee_capture_present": not detect_missing_fee_capture(event_list),
        "mfe_mae_capture_present": not detect_missing_mfe_mae_capture(event_list),
        "live_research_enabled": False,
        "live_trading_for_profit_enabled": False,
        "ml_live_influence_enabled": False,
        "online_learning_started": False,
        "actual_order_placement_integrated": False,
    }


__all__ = [
    "FILL_FIELDS",
    "JOURNAL_FIELDS",
    "LIVE_RESEARCH_JOURNAL_SCHEMA_VERSION",
    "MFE_MAE_FIELDS",
    "RESEARCH_EVENT_TYPES",
    "append_journal_event",
    "build_journal_event",
    "compute_slippage_bps",
    "compute_spread_bps",
    "detect_missing_fee_capture",
    "detect_missing_fill_capture",
    "detect_missing_mfe_mae_capture",
    "live_research_journal_capture_ready",
    "live_research_journal_fail_closed_reasons",
    "live_research_journal_readiness",
    "update_mfe_mae",
    "validate_journal_event",
]
