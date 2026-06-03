"""
Offline Coinbase execution-quality scoring for the controlled spot basket.

This module is intentionally pure and fixture-backed. It does not import broker
clients, read environment variables, place/cancel orders, or mutate state/logs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Iterable, Optional

from coinbase_controlled_live_symbol_expansion import (
    EXCLUDED_SYMBOLS,
    EXPANDED_LIVE_SYMBOLS,
    normalize_symbol,
    product_is_forbidden,
)


SCHEMA_VERSION = "p2-025a.coinbase_execution_quality_registry.v1"
DEFAULT_MAKER_FEE_RATE = Decimal("0.0060")
DEFAULT_TAKER_FEE_RATE = Decimal("0.0120")
DEFAULT_SLIPPAGE_BUFFER_RATE = Decimal("0.0010")
DEFAULT_NOTIONAL_TARGET = Decimal("5.00")
LIQUIDITY_TYPES = {"maker", "taker"}


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _decimal(value: Any, default: Decimal) -> Decimal:
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None else default


def _fmt_decimal(value: Optional[Decimal], places: str = "0.000000") -> Optional[str]:
    if value is None:
        return None
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _fmt_money(value: Optional[Decimal]) -> Optional[str]:
    return _fmt_decimal(value, "0.0000")


def _fmt_pct(value: Optional[Decimal]) -> Optional[str]:
    return _fmt_decimal(value, "0.0001")


def _product_id(symbol: str, row: Dict[str, Any]) -> str:
    existing = str(row.get("product_id") or "").strip().upper()
    if existing:
        return existing.replace("/", "-")
    return normalize_symbol(symbol).replace("/", "-")


def _liquidity_type(value: Any, default: str) -> str:
    text = str(value or default).strip().lower()
    return text if text in LIQUIDITY_TYPES else default


def _fee_rate_for(liquidity_type: str, maker_fee_rate: Decimal, taker_fee_rate: Decimal) -> Decimal:
    return maker_fee_rate if liquidity_type == "maker" else taker_fee_rate


def _spread_pct(bid: Optional[Decimal], ask: Optional[Decimal]) -> Optional[Decimal]:
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / Decimal("2")
    return ((ask - bid) / mid) * Decimal("100")


def _execution_quality_score(
    *,
    verdict: str,
    spread_pct: Optional[Decimal],
    required_break_even_move_rate: Optional[Decimal],
    expected_gross_move_rate: Optional[Decimal],
) -> Decimal:
    verdict_base = {
        "pass": Decimal("100"),
        "observe_only": Decimal("50"),
        "fail": Decimal("0"),
    }.get(verdict, Decimal("0"))
    spread_penalty = (spread_pct or Decimal("10")) * Decimal("10")
    required_penalty = (required_break_even_move_rate or Decimal("1")) * Decimal("100")
    edge_bonus = Decimal("0")
    if expected_gross_move_rate is not None and required_break_even_move_rate is not None:
        edge_bonus = max(Decimal("0"), expected_gross_move_rate - required_break_even_move_rate) * Decimal("1000")
    score = verdict_base + edge_bonus - spread_penalty - required_penalty
    return max(Decimal("0"), score)


def _preview_pnl_note(row: Dict[str, Any]) -> Dict[str, Any]:
    preview_values = [
        row.get("preview_pnl"),
        row.get("preview_profit"),
        row.get("preview_pnl_rate"),
        row.get("order_preview_pnl"),
    ]
    return {
        "provided": any(value is not None for value in preview_values),
        "advisory_only": True,
        "usable_for_final_profitability": False,
        "reason": "coinbase_preview_pnl_excludes_fees_and_slippage",
    }


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def evaluate_symbol_execution_quality(
    row: Dict[str, Any],
    *,
    defaults: Optional[Dict[str, Any]] = None,
    live_symbols: Iterable[str] = EXPANDED_LIVE_SYMBOLS,
    excluded_symbols: Iterable[str] = EXCLUDED_SYMBOLS,
) -> Dict[str, Any]:
    defaults = defaults if isinstance(defaults, dict) else {}
    symbol = normalize_symbol(row.get("symbol") or row.get("product_id"))
    product_id = _product_id(symbol, row)
    bid = _decimal_or_none(row.get("bid"))
    ask = _decimal_or_none(row.get("ask"))
    spread_pct = _spread_pct(bid, ask)
    max_allowed_spread_pct = _decimal(
        row.get("max_allowed_spread_pct") or row.get("max_spread_pct") or defaults.get("max_allowed_spread_pct"),
        Decimal("0.20"),
    )
    notional_target = _decimal(row.get("notional_target") or defaults.get("notional_target"), DEFAULT_NOTIONAL_TARGET)
    maker_fee_rate = _decimal(row.get("maker_fee_rate") or defaults.get("maker_fee_rate"), DEFAULT_MAKER_FEE_RATE)
    taker_fee_rate = _decimal(row.get("taker_fee_rate") or defaults.get("taker_fee_rate"), DEFAULT_TAKER_FEE_RATE)
    entry_liquidity = _liquidity_type(
        row.get("assumed_entry_liquidity_type") or defaults.get("assumed_entry_liquidity_type"),
        "maker",
    )
    exit_liquidity = _liquidity_type(
        row.get("assumed_exit_liquidity_type") or defaults.get("assumed_exit_liquidity_type"),
        "maker",
    )
    round_trip_fee_rate = (
        _fee_rate_for(entry_liquidity, maker_fee_rate, taker_fee_rate)
        + _fee_rate_for(exit_liquidity, maker_fee_rate, taker_fee_rate)
    )
    slippage_buffer_rate = _decimal(
        row.get("slippage_buffer_rate") or defaults.get("slippage_buffer_rate"),
        DEFAULT_SLIPPAGE_BUFFER_RATE,
    )
    expected_gross_move_rate = _decimal_or_none(
        row.get("expected_gross_move_rate") or defaults.get("expected_gross_move_rate")
    )

    reasons: list[str] = []
    live_set = set(normalize_symbol(symbol_value) for symbol_value in live_symbols)
    excluded_set = set(normalize_symbol(symbol_value) for symbol_value in excluded_symbols)
    policy = {"no_derivatives": True, "block_prediction_products": True}

    if not symbol:
        reasons.append("symbol_missing")
    if symbol in excluded_set:
        reasons.append("symbol_excluded_external_inventory")
    if symbol and symbol not in live_set:
        reasons.append("symbol_not_in_controlled_live_basket")
    if product_is_forbidden(product_id, policy) or product_is_forbidden(symbol, policy):
        reasons.append("product_out_of_scope")

    product_type = str(row.get("product_type") or row.get("product_kind") or "spot").strip().lower()
    if product_type and product_type not in {"spot", "spot_crypto", "crypto_spot"}:
        reasons.append("product_out_of_scope")

    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask <= bid:
        reasons.append("invalid_or_stale_quote")
    elif spread_pct is not None and spread_pct > max_allowed_spread_pct:
        reasons.append("spread_too_wide")

    spread_rate = (spread_pct / Decimal("100")) if spread_pct is not None else None
    required_break_even_move_rate = None
    if spread_rate is not None:
        required_break_even_move_rate = round_trip_fee_rate + spread_rate + slippage_buffer_rate

    if expected_gross_move_rate is None:
        reasons.append("expected_gross_move_rate_missing")
    elif required_break_even_move_rate is not None and expected_gross_move_rate <= required_break_even_move_rate:
        reasons.append("expected_gross_move_below_required_break_even")

    preview_note = _preview_pnl_note(row)
    if preview_note["provided"]:
        reasons.append("preview_pnl_advisory_only")

    fail_reasons = {
        "symbol_missing",
        "symbol_excluded_external_inventory",
        "symbol_not_in_controlled_live_basket",
        "product_out_of_scope",
        "invalid_or_stale_quote",
        "spread_too_wide",
        "expected_gross_move_below_required_break_even",
    }
    deduped = _dedupe(reasons)
    if any(reason in fail_reasons for reason in deduped):
        verdict = "fail"
    elif "expected_gross_move_rate_missing" in deduped:
        verdict = "observe_only"
    else:
        verdict = "pass"

    score = _execution_quality_score(
        verdict=verdict,
        spread_pct=spread_pct,
        required_break_even_move_rate=required_break_even_move_rate,
        expected_gross_move_rate=expected_gross_move_rate,
    )

    return {
        "product_id": product_id,
        "symbol": symbol,
        "bid": _fmt_money(bid),
        "ask": _fmt_money(ask),
        "spread_pct": _fmt_pct(spread_pct),
        "max_allowed_spread_pct": _fmt_pct(max_allowed_spread_pct),
        "notional_target": _fmt_money(notional_target),
        "maker_fee_rate": _fmt_decimal(maker_fee_rate),
        "taker_fee_rate": _fmt_decimal(taker_fee_rate),
        "assumed_entry_liquidity_type": entry_liquidity,
        "assumed_exit_liquidity_type": exit_liquidity,
        "round_trip_fee_rate": _fmt_decimal(round_trip_fee_rate),
        "slippage_buffer_rate": _fmt_decimal(slippage_buffer_rate),
        "required_break_even_move_rate": _fmt_decimal(required_break_even_move_rate),
        "expected_gross_move_rate": _fmt_decimal(expected_gross_move_rate),
        "execution_quality_score": _fmt_decimal(score, "0.0000"),
        "verdict": verdict,
        "reasons": deduped,
        "preview_pnl": {
            "value": row.get("preview_pnl") or row.get("preview_profit") or row.get("order_preview_pnl"),
            **preview_note,
        },
    }


def build_execution_quality_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    live_symbols = payload.get("live_symbols") if isinstance(payload.get("live_symbols"), list) else list(EXPANDED_LIVE_SYMBOLS)
    excluded_symbols = (
        payload.get("excluded_symbols") if isinstance(payload.get("excluded_symbols"), list) else list(EXCLUDED_SYMBOLS)
    )
    rows = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []

    evaluations = [
        evaluate_symbol_execution_quality(
            row,
            defaults=defaults,
            live_symbols=live_symbols,
            excluded_symbols=excluded_symbols,
        )
        for row in rows
        if isinstance(row, dict)
    ]

    live_set = set(normalize_symbol(symbol) for symbol in live_symbols)
    excluded_set = set(normalize_symbol(symbol) for symbol in excluded_symbols)
    ranked_symbols = [
        row
        for row in evaluations
        if row["symbol"] in live_set
        and row["symbol"] not in excluded_set
        and "product_out_of_scope" not in row["reasons"]
    ]
    ranked_symbols.sort(
        key=lambda row: (
            {"pass": 0, "observe_only": 1, "fail": 2}.get(row["verdict"], 9),
            -float(row["execution_quality_score"]),
            row["symbol"],
        )
    )
    for idx, row in enumerate(ranked_symbols, start=1):
        row["rank"] = idx

    out_of_scope = [row for row in evaluations if row not in ranked_symbols]
    pass_count = sum(1 for row in ranked_symbols if row["verdict"] == "pass")
    observe_count = sum(1 for row in ranked_symbols if row["verdict"] == "observe_only")

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "offline_fixture_backed_read_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS_CANDIDATES_AVAILABLE" if pass_count else ("OBSERVE_ONLY" if observe_count else "NO_PASSING_SYMBOLS"),
        "trade_permission": "none",
        "preview_pnl_policy": {
            "advisory_only": True,
            "usable_for_final_profitability": False,
            "reason": "coinbase_preview_pnl_excludes_fees_and_slippage",
        },
        "ranking_basis": [
            "controlled_live_spot_basket_only",
            "bid_ask_spread",
            "maker_taker_fee_assumptions",
            "slippage_buffer",
            "required_break_even_move_rate",
            "expected_gross_move_rate_when_supplied",
        ],
        "live_symbols": [normalize_symbol(symbol) for symbol in live_symbols],
        "excluded_symbols": [normalize_symbol(symbol) for symbol in excluded_symbols],
        "ranked_symbols": ranked_symbols,
        "out_of_scope_symbols": out_of_scope,
        "summary": {
            "ranked_symbol_count": len(ranked_symbols),
            "pass_count": pass_count,
            "observe_only_count": observe_count,
            "fail_count": sum(1 for row in ranked_symbols if row["verdict"] == "fail"),
            "best_symbol": ranked_symbols[0]["symbol"] if ranked_symbols else None,
            "sol_excluded": any(row["symbol"] == "SOL/USD" for row in out_of_scope),
            "profit_readout": "unsafe_to_aggregate",
            "risk_increase": "not_approved",
        },
        "safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "secrets_or_env_read": False,
            "orders_cancels_closes_modifications": False,
            "state_or_log_mutation": False,
            "runtime_restart_performed": False,
            "runtime_control_touched": False,
            "trade_permission": "none",
        },
    }
