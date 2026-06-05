#!/usr/bin/env python3
"""
P2-025W historical signal generator.

Offline-only. Iterates local OHLCV bars, invokes the P2-025V offline strategy
runner adapter, and emits synthetic cycle records for expanded validation.
No broker clients, no network fetches, no runtime mutation, and no live orders.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import (  # noqa: E402
    DEFAULT_MAX_HOLD_MINUTES,
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
    Bar,
    _normalize_symbol,
    load_bars_from_fixture,
)
from market_data import add_indicators  # noqa: E402
from risk_manager import TradeProposal  # noqa: E402
from scripts.coinbase_offline_strategy_runner_adapter import (  # noqa: E402
    OfflineMarketDataAdapter,
    STRATEGY_LOGIC_IMPORTABLE,
    CryptoStrategy,
    REGIME_STRATEGIES,
    _model_quote_from_bar,
    classify_regime,
)

SCHEMA_VERSION = "p2-026a.coinbase_historical_signal_generator.v1"
DATA_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"
MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")
DEFAULT_NOTIONAL = Decimal("5")
DEFAULT_SPREAD_PCT = Decimal("0.10")

PRE_ENTRY_FEATURE_SCHEMA = {
    "numeric_fields": [
        "pre_entry_return_1",
        "pre_entry_return_3",
        "pre_entry_return_6",
        "pre_entry_return_12",
        "pre_entry_volatility_6",
        "pre_entry_volatility_12",
        "pre_entry_atr_14",
        "pre_entry_range_pct_1",
        "pre_entry_range_pct_3",
        "pre_entry_volume",
        "pre_entry_volume_sma_12",
        "pre_entry_volume_ratio_12",
        "pre_entry_hour_utc",
    ],
    "categorical_fields": [
        "pre_entry_liquidity_bucket",
        "pre_entry_volatility_bucket",
        "pre_entry_momentum_bucket",
        "pre_entry_atr_bucket",
        "pre_entry_day_of_week_utc",
        "pre_entry_session_bucket",
        "pre_entry_regime",
        "pre_entry_confidence",
        "pre_entry_symbol_strategy_key",
    ],
    "order_book_fields": [
        "order_book_spread_available",
        "bid_ask_depth_available",
        "order_book_features_missing_reason",
    ],
    "leakage_contract": {
        "uses_bars_through_entry_only": True,
        "uses_exit_reason": False,
        "uses_future_path": False,
    },
}


def _fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _fmt_rate(value: Decimal) -> str:
    return str(value.quantize(RATE_QUANT, rounding=ROUND_HALF_UP))


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


def _return_over_bars(history_bars: Sequence[Bar], periods: int) -> Decimal:
    if len(history_bars) <= periods:
        return Decimal("0")
    current = history_bars[-1].c
    prior = history_bars[-1 - periods].c
    return _safe_ratio(current - prior, prior)


def _range_pct(bar: Bar) -> Decimal:
    return _safe_ratio(bar.h - bar.l, bar.c)


def _rolling_return_volatility(history_bars: Sequence[Bar], periods: int) -> Decimal:
    if len(history_bars) <= periods:
        return Decimal("0")
    closes = [bar.c for bar in history_bars[-(periods + 1):]]
    returns = [
        float(_safe_ratio(closes[idx] - closes[idx - 1], closes[idx - 1]))
        for idx in range(1, len(closes))
    ]
    if not returns:
        return Decimal("0")
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return Decimal(str(math.sqrt(variance)))


def _atr_proxy_pct(history_bars: Sequence[Bar], periods: int = 14) -> Decimal:
    if not history_bars:
        return Decimal("0")
    window = list(history_bars[-periods:])
    true_ranges: List[Decimal] = []
    start_index = len(history_bars) - len(window)
    for offset, bar in enumerate(window):
        absolute_index = start_index + offset
        prior_close = history_bars[absolute_index - 1].c if absolute_index > 0 else bar.c
        true_range = max(
            bar.h - bar.l,
            abs(bar.h - prior_close),
            abs(bar.l - prior_close),
        )
        true_ranges.append(true_range)
    atr = _sum_decimal(true_ranges) / Decimal(len(true_ranges)) if true_ranges else Decimal("0")
    return _safe_ratio(atr, history_bars[-1].c)


def _sum_decimal(values: Iterable[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += value
    return total


def _bucket_signed_rate(value: Decimal) -> str:
    if value <= Decimal("-0.01"):
        return "<=-1%"
    if value <= Decimal("-0.005"):
        return "-1%--0.5%"
    if value < Decimal("0"):
        return "-0.5%-0"
    if value == 0:
        return "0"
    if value < Decimal("0.005"):
        return "0-0.5%"
    if value < Decimal("0.01"):
        return "0.5%-1%"
    return ">=1%"


def _bucket_positive_rate(value: Decimal) -> str:
    if value == 0:
        return "0"
    if value < Decimal("0.0025"):
        return "0-0.25%"
    if value < Decimal("0.005"):
        return "0.25%-0.5%"
    if value < Decimal("0.01"):
        return "0.5%-1%"
    if value < Decimal("0.02"):
        return "1%-2%"
    return ">=2%"


def _volume_bucket(ratio: Decimal) -> str:
    if ratio == 0:
        return "unknown"
    if ratio < Decimal("0.50"):
        return "thin_<0.5x"
    if ratio < Decimal("0.90"):
        return "below_avg_0.5x_0.9x"
    if ratio <= Decimal("1.10"):
        return "normal_0.9x_1.1x"
    if ratio <= Decimal("1.50"):
        return "elevated_1.1x_1.5x"
    return "high_>1.5x"


def _session_bucket(hour: int) -> str:
    if hour < 6:
        return "00-05"
    if hour < 12:
        return "06-11"
    if hour < 18:
        return "12-17"
    return "18-23"


def _pre_entry_features(
    *,
    symbol: str,
    strategy: str,
    history_bars: Sequence[Bar],
    regime: Optional[str],
    confidence: Any,
) -> Dict[str, Any]:
    entry_bar = history_bars[-1]
    return_1 = _return_over_bars(history_bars, 1)
    return_3 = _return_over_bars(history_bars, 3)
    return_6 = _return_over_bars(history_bars, 6)
    return_12 = _return_over_bars(history_bars, 12)
    volatility_6 = _rolling_return_volatility(history_bars, 6)
    volatility_12 = _rolling_return_volatility(history_bars, 12)
    atr_14 = _atr_proxy_pct(history_bars, 14)
    range_1 = _range_pct(entry_bar)
    recent_ranges = [_range_pct(bar) for bar in history_bars[-3:]]
    range_3 = _sum_decimal(recent_ranges) / Decimal(len(recent_ranges)) if recent_ranges else Decimal("0")
    volume = entry_bar.v
    volume_window = [bar.v for bar in history_bars[-12:]]
    volume_sma_12 = _sum_decimal(volume_window) / Decimal(len(volume_window)) if volume_window else Decimal("0")
    volume_ratio_12 = _safe_ratio(volume, volume_sma_12)
    hour = entry_bar.t.hour
    day_name = entry_bar.t.strftime("%a")
    confidence_value = _to_decimal(confidence, Decimal("0"))
    return {
        "pre_entry_return_1": _fmt_rate(return_1),
        "pre_entry_return_3": _fmt_rate(return_3),
        "pre_entry_return_6": _fmt_rate(return_6),
        "pre_entry_return_12": _fmt_rate(return_12),
        "pre_entry_volatility_6": _fmt_rate(volatility_6),
        "pre_entry_volatility_12": _fmt_rate(volatility_12),
        "pre_entry_atr_14": _fmt_rate(atr_14),
        "pre_entry_range_pct_1": _fmt_rate(range_1),
        "pre_entry_range_pct_3": _fmt_rate(range_3),
        "pre_entry_volume": _fmt_money(volume),
        "pre_entry_volume_sma_12": _fmt_money(volume_sma_12),
        "pre_entry_volume_ratio_12": _fmt_rate(volume_ratio_12),
        "pre_entry_liquidity_bucket": _volume_bucket(volume_ratio_12),
        "pre_entry_volatility_bucket": _bucket_positive_rate(volatility_12),
        "pre_entry_momentum_bucket": _bucket_signed_rate(return_12),
        "pre_entry_atr_bucket": _bucket_positive_rate(atr_14),
        "pre_entry_hour_utc": hour,
        "pre_entry_day_of_week_utc": day_name,
        "pre_entry_session_bucket": _session_bucket(hour),
        "pre_entry_regime": regime or "unknown",
        "pre_entry_confidence": _fmt_rate(confidence_value),
        "pre_entry_symbol_strategy_key": f"{symbol}|{strategy}",
        "order_book_spread_available": False,
        "bid_ask_depth_available": False,
        "order_book_features_missing_reason": "OHLCV-only dataset",
    }


def _rate(wins: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(wins / total, 6)


def _bars_to_df(bars: Sequence[Bar]) -> pd.DataFrame:
    rows = [
        {
            "t": bar.t,
            "o": float(bar.o),
            "h": float(bar.h),
            "l": float(bar.l),
            "c": float(bar.c),
            "v": float(bar.v),
        }
        for bar in bars
    ]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.set_index("t").sort_index()
    return add_indicators(df)


def _discover_ohlcv_files(data_dir: Path, symbol: Optional[str] = None) -> List[Path]:
    if not data_dir.exists():
        return []
    files = sorted(data_dir.glob("*.csv")) + sorted(data_dir.glob("*.json"))
    if not symbol:
        return files
    wanted = _normalize_symbol(symbol)
    candidates = []
    for path in files:
        upper = path.name.upper()
        dash = wanted.replace("/", "-")
        flat = wanted.replace("/", "")
        if dash in upper or flat in upper:
            candidates.append(path)
    return candidates


def _load_ohlcv_inventory(data_dir: Path, symbol: Optional[str] = None, max_bars: Optional[int] = None) -> List[Dict[str, Any]]:
    inventory: List[Dict[str, Any]] = []
    for path in _discover_ohlcv_files(data_dir, symbol=symbol):
        bars = load_bars_from_fixture(path, symbol=symbol)
        if max_bars:
            bars = bars[:max_bars]
        if not bars:
            continue
        inferred_symbol = _normalize_symbol(bars[0].symbol or path.name.split("_", 1)[0])
        inventory.append(
            {
                "path": path,
                "file": path.name,
                "symbol": inferred_symbol,
                "bars": bars,
                "start": bars[0].t,
                "end": bars[-1].t,
                "bar_count": len(bars),
            }
        )
    return inventory


def _offline_cfg_getter(*keys, **kwargs):
    default = kwargs.get("default")
    cfg = {
        "strategy": {
            "prefer_no_trade_when_unclear": True,
            "lookback_bars": 20,
            "min_confidence_score": 0.70,
        },
        "strategy_thresholds": {
            "confidence_threshold": {
                "momentum_breakout": 0.70,
                "mean_reversion": 0.72,
                "ema_crossover": 0.68,
            }
        },
        "crypto": {
            "bars_limit": 100,
            "min_bars_required": 10,
            "use_atr_exits": True,
            "stop_loss_pct": float(DEFAULT_STOP_LOSS_PCT),
            "take_profit_pct": float(DEFAULT_TAKE_PROFIT_PCT),
            "slippage_estimate_pct": 0.05,
            "coinbase_probe_enabled": False,
            "controlled_exploration": {"enabled": False},
        },
        "fees": {
            "maker_fee_pct": 0.0015,
            "taker_fee_pct": 0.0025,
            "require_expected_edge_pct": 0.006,
        },
        "risk": {
            "min_trade_notional_usd": 0.50,
            "max_trade_notional_usd": 5.00,
        },
    }
    if not keys:
        return default
    value: Any = cfg
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


def _run_strategy_methods_for_bar(
    *,
    symbol: str,
    history_bars: Sequence[Bar],
    spread_pct: Decimal,
    history_df: Optional[pd.DataFrame] = None,
) -> Tuple[List[TradeProposal], Optional[str]]:
    if not STRATEGY_LOGIC_IMPORTABLE or not history_bars:
        return [], None
    df = history_df if history_df is not None else _bars_to_df(history_bars)
    if df.empty:
        return [], None
    try:
        regime = classify_regime(df)
    except Exception:
        regime = "range"
    quote = _model_quote_from_bar(df.iloc[-1], spread_pct=float(spread_pct))
    quote.symbol = symbol
    adapter = OfflineMarketDataAdapter(df, quote)
    strategy = CryptoStrategy(adapter)
    proposals: List[TradeProposal] = []
    allowed = REGIME_STRATEGIES.get(regime, [])
    with patch("strategy_crypto.get_cfg", side_effect=_offline_cfg_getter):
        for strategy_name in allowed:
            method = getattr(strategy, f"_{strategy_name}", None)
            if method is None:
                continue
            try:
                if strategy_name == "momentum_breakout":
                    proposal = method(symbol, quote, df, True, 100.0, 20, regime)
                else:
                    proposal = method(symbol, quote, df, True, 100.0, regime)
            except Exception:
                proposal = None
            if proposal is not None:
                proposals.append(proposal)
    return proposals, regime


def _entry_price_from_bar(
    bar: Bar,
    *,
    entry_basis: str,
    spread_pct: Decimal,
) -> Tuple[Decimal, Decimal]:
    close = bar.c
    if entry_basis == "close":
        return close, Decimal("0")
    if entry_basis == "close_plus_spread":
        adjustment = close * (spread_pct / Decimal("100"))
        return close + adjustment, spread_pct
    raise ValueError(f"unsupported entry_basis={entry_basis}")


def _simulate_exit(
    *,
    bars: Sequence[Bar],
    entry_index: int,
    entry_price: Decimal,
    proposal: TradeProposal,
    max_hold_minutes: int,
) -> Tuple[int, Bar, Decimal, str, str]:
    fallback_index = entry_index
    fallback_bar = bars[entry_index]
    stop_price = _to_decimal(proposal.stop_loss_price)
    take_profit_price = _to_decimal(proposal.take_profit_price)
    if stop_price <= 0:
        stop_price = entry_price * (Decimal("1") - (DEFAULT_STOP_LOSS_PCT / Decimal("100")))
    if take_profit_price <= 0:
        take_profit_price = entry_price * (Decimal("1") + (DEFAULT_TAKE_PROFIT_PCT / Decimal("100")))
    target_time = bars[entry_index].t + timedelta(minutes=max_hold_minutes)

    for idx in range(entry_index + 1, len(bars)):
        bar = bars[idx]
        fallback_index = idx
        fallback_bar = bar
        price = bar.c
        if price <= stop_price:
            return idx, bar, price, "stop-loss hit", "close_scan_stop_loss_after_entry"
        if price >= take_profit_price:
            return idx, bar, price, "take-profit hit", "close_scan_take_profit_after_entry"
        if bar.t >= target_time:
            return idx, bar, price, f"max hold time {max_hold_minutes}min exceeded", "close_scan_timeout_after_entry"

    return fallback_index, fallback_bar, fallback_bar.c, "end_of_data", "last_available_close_after_entry"


def _cycle_from_signal(
    *,
    symbol: str,
    source_file: str,
    bars: Sequence[Bar],
    entry_index: int,
    proposal: TradeProposal,
    regime: Optional[str],
    entry_basis: str,
    spread_pct: Decimal,
    max_hold_minutes: int,
) -> Tuple[Dict[str, Any], int]:
    entry_bar = bars[entry_index]
    entry_price, entry_spread = _entry_price_from_bar(entry_bar, entry_basis=entry_basis, spread_pct=spread_pct)
    exit_index, exit_bar, exit_price, exit_reason, exit_basis = _simulate_exit(
        bars=bars,
        entry_index=entry_index,
        entry_price=entry_price,
        proposal=proposal,
        max_hold_minutes=max_hold_minutes,
    )
    notional = _to_decimal(proposal.notional, DEFAULT_NOTIONAL)
    if notional <= 0:
        notional = DEFAULT_NOTIONAL
    qty = notional / entry_price if entry_price > 0 else Decimal("0")
    gross = (exit_price - entry_price) * qty
    pnl_pct = (gross / notional) if notional > 0 else Decimal("0")
    hold_minutes = Decimal(str((exit_bar.t - entry_bar.t).total_seconds() / 60.0))
    meta = proposal.meta or {}
    pre_entry_features = _pre_entry_features(
        symbol=symbol,
        strategy=proposal.strategy,
        history_bars=bars[: entry_index + 1],
        regime=regime or meta.get("regime"),
        confidence=proposal.confidence,
    )
    cycle = {
        "synthetic": True,
        "symbol": symbol,
        "strategy": proposal.strategy,
        "entry_time": entry_bar.t.isoformat(),
        "exit_time": exit_bar.t.isoformat(),
        "entry_price": _fmt_money(entry_price),
        "exit_price": _fmt_money(exit_price),
        "qty": _fmt_money(qty),
        "notional": _fmt_money(notional),
        "gross_pnl": _fmt_money(gross),
        "fees_paid": "0.00000000",
        "pnl_usd": _fmt_money(gross),
        "pnl_pct": _fmt_rate(pnl_pct),
        "confidence": proposal.confidence,
        "regime": regime or meta.get("regime"),
        "exit_reason": exit_reason,
        "hold_duration_minutes": str(hold_minutes.quantize(Decimal("0.000001"))),
        "entry_spread_pct": _fmt_rate(entry_spread),
        "entry_basis": entry_basis,
        "exit_basis": exit_basis,
        "source_ohlcv_file": source_file,
        **pre_entry_features,
        "leakage_guard": {
            "signal_bar_time": entry_bar.t.isoformat(),
            "history_last_time": entry_bar.t.isoformat(),
            "exit_first_allowed_time": bars[entry_index + 1].t.isoformat() if entry_index + 1 < len(bars) else None,
            "no_future_bars_for_signal": True,
            "exit_after_entry_only": exit_index > entry_index,
            "no_journal_exit_leakage": True,
            "pre_entry_features_use_only_past_bars": True,
            "no_exit_reason_in_pre_entry_features": True,
            "no_future_path_in_pre_entry_features": True,
        },
    }
    return cycle, exit_index


def _summaries(cycles: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    gross_values = [_to_decimal(c.get("gross_pnl")) for c in cycles]
    wins = sum(1 for value in gross_values if value > 0)
    losses = sum(1 for value in gross_values if value < 0)
    total = sum(gross_values, Decimal("0"))
    avg = total / len(gross_values) if gross_values else Decimal("0")
    med = Decimal(str(median([float(v) for v in gross_values]))) if gross_values else Decimal("0")

    def grouped(field: str) -> Dict[str, Dict[str, Any]]:
        groups: Dict[str, List[Decimal]] = defaultdict(list)
        for cycle, gross in zip(cycles, gross_values):
            groups[str(cycle.get(field, "unknown"))].append(gross)
        payload: Dict[str, Dict[str, Any]] = {}
        for key, values in sorted(groups.items()):
            w = sum(1 for value in values if value > 0)
            l = sum(1 for value in values if value < 0)
            payload[key] = {
                "cycles": len(values),
                "gross_total": _fmt_money(sum(values, Decimal("0"))),
                "win_rate": _rate(w, len(values)),
                "winner_count": w,
                "loser_count": l,
            }
        return payload

    gross_summary = {
        "gross_total": _fmt_money(total),
        "avg_gross": _fmt_money(avg),
        "median_gross": _fmt_money(med),
        "win_rate": _rate(wins, len(gross_values)),
        "winner_count": wins,
        "loser_count": losses,
    }
    return (
        gross_summary,
        grouped("symbol"),
        grouped("strategy"),
        grouped("exit_reason"),
    )


def build_historical_signal_generator_report(
    *,
    data_dir: Optional[Path] = None,
    symbol: Optional[str] = None,
    max_bars: Optional[int] = None,
    max_cycles: Optional[int] = None,
    entry_basis: str = "close",
    max_hold_minutes: int = DEFAULT_MAX_HOLD_MINUTES,
    spread_pct: Decimal = DEFAULT_SPREAD_PCT,
    max_open_positions: int = 1,
    max_trades_per_day: int = 999,
    cooldown_bars: int = 0,
) -> Dict[str, Any]:
    dpath = Path(data_dir) if data_dir else DATA_DIR
    inventory = _load_ohlcv_inventory(dpath, symbol=symbol, max_bars=max_bars)
    cycles: List[Dict[str, Any]] = []
    signal_candidates_count = 0
    bars_scanned = 0
    symbols_scanned = sorted({item["symbol"] for item in inventory})
    active_until: List[datetime] = []
    daily_trade_counts: Counter[str] = Counter()

    for item in inventory:
        bars: List[Bar] = item["bars"]
        enriched_df = _bars_to_df(bars)
        bars_scanned += len(bars)
        next_allowed_index = 0
        min_history = 25
        for idx in range(min_history, len(bars) - 1):
            if max_cycles is not None and len(cycles) >= max_cycles:
                break
            if idx < next_allowed_index:
                continue
            now = bars[idx].t
            active_until = [t for t in active_until if t > now]
            day_key = now.date().isoformat()
            if len(active_until) >= max_open_positions:
                continue
            if daily_trade_counts[day_key] >= max_trades_per_day:
                continue
            proposals, regime = _run_strategy_methods_for_bar(
                symbol=item["symbol"],
                history_bars=bars[: idx + 1],
                spread_pct=spread_pct,
                history_df=enriched_df.iloc[: idx + 1],
            )
            if not proposals:
                continue
            signal_candidates_count += len(proposals)
            proposal = proposals[0]
            cycle, exit_index = _cycle_from_signal(
                symbol=item["symbol"],
                source_file=item["file"],
                bars=bars,
                entry_index=idx,
                proposal=proposal,
                regime=regime,
                entry_basis=entry_basis,
                spread_pct=spread_pct,
                max_hold_minutes=max_hold_minutes,
            )
            cycles.append(cycle)
            active_until.append(datetime.fromisoformat(cycle["exit_time"]))
            daily_trade_counts[day_key] += 1
            next_allowed_index = max(exit_index + cooldown_bars + 1, idx + 1)
        if max_cycles is not None and len(cycles) >= max_cycles:
            break

    gross_summary, per_symbol, per_strategy, per_exit = _summaries(cycles)
    starts = [item["start"] for item in inventory]
    ends = [item["end"] for item in inventory]
    no_future = all(c["leakage_guard"]["no_future_bars_for_signal"] for c in cycles) if cycles else True
    exit_after = all(c["leakage_guard"]["exit_after_entry_only"] for c in cycles) if cycles else True
    no_journal = all(c["leakage_guard"]["no_journal_exit_leakage"] for c in cycles) if cycles else True
    pre_entry_past = all(
        c["leakage_guard"].get("pre_entry_features_use_only_past_bars") for c in cycles
    ) if cycles else True
    no_exit_reason_features = all(
        c["leakage_guard"].get("no_exit_reason_in_pre_entry_features") for c in cycles
    ) if cycles else True
    no_future_path_features = all(
        c["leakage_guard"].get("no_future_path_in_pre_entry_features") for c in cycles
    ) if cycles else True

    synthetic_ready = len(cycles) > 0
    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "historical_signal_generator",
        "data_dir": str(dpath),
        "symbols_scanned": symbols_scanned,
        "bars_scanned": bars_scanned,
        "date_range": {
            "start": min(starts).isoformat() if starts else None,
            "end": max(ends).isoformat() if ends else None,
        },
        "signal_candidates_count": signal_candidates_count,
        "synthetic_cycles_count": len(cycles),
        "per_symbol_summary": per_symbol,
        "per_strategy_summary": per_strategy,
        "per_exit_reason_summary": per_exit,
        "gross_summary": gross_summary,
        "pre_entry_feature_schema": PRE_ENTRY_FEATURE_SCHEMA,
        "synthetic_cycles": cycles,
        "generated_cycle_sample": cycles[:5],
        "leakage_guards": {
            "no_future_bars_for_signal": no_future,
            "exit_after_entry_only": exit_after,
            "no_journal_exit_leakage": no_journal,
            "pre_entry_features_use_only_past_bars": pre_entry_past,
            "no_exit_reason_in_pre_entry_features": no_exit_reason_features,
            "no_future_path_in_pre_entry_features": no_future_path_features,
        },
        "readiness": {
            "historical_signal_generator_ready": STRATEGY_LOGIC_IMPORTABLE and bars_scanned > 0,
            "synthetic_cycle_journal_ready": synthetic_ready,
            "expanded_filter_validation_ready": synthetic_ready,
        },
        "adapter_functions_used": [
            "OfflineMarketDataAdapter",
            "_model_quote_from_bar",
            "classify_regime",
            "CryptoStrategy._momentum_breakout",
            "CryptoStrategy._mean_reversion",
            "CryptoStrategy._ema_crossover",
            "add_indicators",
        ],
        "live_dependencies_bypassed_or_mocked": [
            "MarketData broker fetches",
            "strategy_crypto.get_cfg",
            "position and journal state",
            "risk manager order approval",
            "broker order placement",
        ],
        "state_model": {
            "one_open_position_per_symbol": True,
            "max_open_positions_analysis_only": max_open_positions,
            "max_trades_per_day_analysis_only": max_trades_per_day,
            "cooldown_bars_analysis_only": cooldown_bars,
        },
        "limitations": [
            "Synthetic cycles are offline candidates, not live broker results.",
            "OHLCV lacks real bid/ask and queue-position data.",
            "fees_paid is zero by default for gross-edge analysis.",
            "No profitability claim is made from generated cycles without separate validation.",
            "Controlled exploration/state-heavy paths remain bypassed.",
        ],
        "verdict": {
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "next_step_recommendation": (
            "Run expanded offline filter validation on the generated synthetic cycles."
            if synthetic_ready
            else "No reusable strategy signals were found in the local OHLCV scan; expand data or inspect signal thresholds offline only."
        ),
    }
    return payload


def write_cycles_jsonl(path: Path, cycles: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for cycle in cycles:
            handle.write(json.dumps(cycle, sort_keys=True) + "\n")


def _human_summary(payload: Dict[str, Any]) -> str:
    lines = [
        "=== P2-025W HISTORICAL SIGNAL GENERATOR ===",
        f"data_dir={payload['data_dir']}",
        f"symbols_scanned={payload['symbols_scanned']}",
        f"bars_scanned={payload['bars_scanned']} date_range={payload['date_range']}",
        f"signal_candidates_count={payload['signal_candidates_count']}",
        f"synthetic_cycles_count={payload['synthetic_cycles_count']}",
        "",
        "Gross summary:",
        f"  gross_total={payload['gross_summary']['gross_total']} avg={payload['gross_summary']['avg_gross']} "
        f"median={payload['gross_summary']['median_gross']} win_rate={payload['gross_summary']['win_rate']}",
        "",
        "Readiness:",
    ]
    for key, value in payload["readiness"].items():
        lines.append(f"  {key}={str(value).lower()}")
    lines.extend([
        "",
        f"Leakage guards: {payload['leakage_guards']}",
        "Permission verdict: implementation=false paper=false live=false scaling=false",
        f"Next: {payload['next_step_recommendation']}",
        "=== END REPORT ===",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Historical signal generator (offline only, P2-025W)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--max-bars", type=int, default=None)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--entry-basis", choices=["close", "close_plus_spread"], default="close")
    parser.add_argument("--mode", choices=["report"], default="report")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSONL cycle output; no write by default")
    args = parser.parse_args(argv)

    payload = build_historical_signal_generator_report(
        data_dir=args.data_dir,
        symbol=args.symbol,
        max_bars=args.max_bars,
        max_cycles=args.max_cycles,
        entry_basis=args.entry_basis,
    )
    if args.output:
        write_cycles_jsonl(args.output, payload["synthetic_cycles"])
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(_human_summary(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
