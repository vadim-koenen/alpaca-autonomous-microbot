"""
P2-043C: MFE/MAE Exit Analysis Module
Derives deterministic take-profit, invalidation, and adaptive max-hold parameters
from historical price paths and journal data.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import quantiles, median
from typing import Optional, Dict, List

# Re-use logic from the existing report script where possible
from scripts.coinbase_price_path_mfe_mae_report import (
    read_price_path_csv,
    position_key_from_row,
    PositionKey,
    safe_float,
    parse_iso_timestamp,
)


@dataclass(frozen=True)
class PositionAnalysis:
    symbol: str
    strategy: str
    mfe_pct: float
    mae_pct: float
    time_to_mfe_minutes: float


@dataclass(frozen=True)
class DerivedExitParameters:
    take_profit_pct: float
    invalidation_pct: float
    adaptive_max_hold_minutes: float
    sample_size: int
    is_valid: bool


@dataclass(frozen=True)
class FeeModelAssumptions:
    entry_fee_pct: float = 0.60
    exit_fee_pct: float = 0.60
    spread_slippage_pct: float = 0.10


def calculate_round_trip_cost_pct(fees: FeeModelAssumptions) -> float:
    return fees.entry_fee_pct + fees.exit_fee_pct + fees.spread_slippage_pct


def load_journal_strategies(journal_path: Path) -> Dict[str, str]:
    """Map position_id or order_id to strategy from the journal."""
    strategy_map: Dict[str, str] = {}
    if not journal_path.exists():
        return strategy_map

    try:
        with open(journal_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = row.get("order_id", "").strip()
                client_id = row.get("client_order_id", "").strip()
                strategy = row.get("strategy", "").strip() or "unknown"
                if order_id:
                    strategy_map[order_id] = strategy
                if client_id:
                    strategy_map[client_id] = strategy
    except Exception:
        pass
    return strategy_map


def extract_position_analyses(
    price_path_csv: Path, journal_csv: Path
) -> List[PositionAnalysis]:
    """Read CSVs and build a list of PositionAnalysis objects."""
    strategy_map = load_journal_strategies(journal_csv)
    rows, err = read_price_path_csv(price_path_csv)
    if err or not rows:
        return []

    # Group by position key
    grouped: Dict[PositionKey, List[Dict[str, str]]] = {}
    for row in rows:
        key = position_key_from_row(row)
        if key is None:
            continue
        grouped.setdefault(key, []).append(row)

    analyses: List[PositionAnalysis] = []

    for key, samples in grouped.items():
        if not samples:
            continue

        # Sort samples by time
        samples.sort(
            key=lambda r: (
                parse_iso_timestamp(r.get("timestamp_utc", ""))
                or datetime.min.replace(tzinfo=timezone.utc)
            )
        )

        unrealized_values: List[float] = []
        mfe_pct = -float('inf')
        mae_pct = float('inf')
        time_to_mfe = 0.0

        for row in samples:
            u = safe_float(row.get("unrealized_pct"))
            h = safe_float(row.get("hold_minutes"))
            if u is not None:
                unrealized_values.append(u)
                if u > mfe_pct:
                    mfe_pct = u
                    time_to_mfe = h if h is not None else time_to_mfe
                if u < mae_pct:
                    mae_pct = u

        if not unrealized_values:
            continue

        strategy = strategy_map.get(key.position_id, "unknown")

        analyses.append(
            PositionAnalysis(
                symbol=key.symbol,
                strategy=strategy,
                mfe_pct=mfe_pct,
                mae_pct=mae_pct,
                time_to_mfe_minutes=time_to_mfe,
            )
        )

    return analyses


def derive_parameters_for_group(
    analyses: List[PositionAnalysis],
    fee_model: FeeModelAssumptions = FeeModelAssumptions(),
    min_samples: int = 5,
) -> DerivedExitParameters:
    """
    Derive deterministic TP, SL, and max-hold from a group of PositionAnalysis.
    """
    if len(analyses) < min_samples:
        return DerivedExitParameters(0.0, 0.0, 0.0, len(analyses), False)

    mfes = [a.mfe_pct for a in analyses]
    maes = [a.mae_pct for a in analyses]
    times_to_mfe = [a.time_to_mfe_minutes for a in analyses]

    # Calculate base percentiles
    # TP: 40th percentile of MFE. We don't want the absolute max, nor the median.
    # 40th percentile means 60% of trades reached at least this MFE.
    # We must ensure it reliably clears round-trip costs.
    try:
        # quantiles(n=10) splits into 10 buckets, so index 3 is the 40th percentile.
        mfe_40 = quantiles(mfes, n=10)[3]
    except ValueError:
        mfe_40 = median(mfes)

    # Invalidation (SL): 20th percentile of MAE (i.e., very adverse).
    # We want to cut losers early. If it goes past the 20th percentile of all MAEs, it's dead.
    try:
        mae_20 = quantiles(maes, n=10)[1]
    except ValueError:
        mae_20 = min(maes)

    # Adaptive max-hold: 80th percentile of time-to-MFE.
    # If 80% of trades hit their max favorable excursion by minute X, holding longer is pure bleed.
    try:
        time_80 = quantiles(times_to_mfe, n=10)[7]
    except ValueError:
        time_80 = max(times_to_mfe)

    # Apply net-of-fee awareness
    rt_cost = calculate_round_trip_cost_pct(fee_model)
    min_target = rt_cost * 1.5  # Need some margin over costs

    if mfe_40 < min_target:
        # Rejected: The observed MFE distribution cannot clear round-trip fee + spread/slippage + margin.
        return DerivedExitParameters(0.0, 0.0, 0.0, len(analyses), False)

    tp_pct = mfe_40

    # Cap invalidation to a sane value so we don't hold to -10% just because data says so
    sl_pct = max(mae_20, -5.0)

    # Cap hold time at 120 mins max, 10 mins min
    max_hold = max(min(time_80, 120.0), 10.0)

    return DerivedExitParameters(
        take_profit_pct=tp_pct,
        invalidation_pct=sl_pct,
        adaptive_max_hold_minutes=max_hold,
        sample_size=len(analyses),
        is_valid=True,
    )


def generate_exit_parameter_cache(
    price_path_csv: Path, journal_csv: Path
) -> Dict[str, DerivedExitParameters]:
    """
    Returns a mapping of "{symbol}_{strategy}" to DerivedExitParameters.
    Includes a fallback "GLOBAL_FALLBACK" key.
    """
    analyses = extract_position_analyses(price_path_csv, journal_csv)

    grouped: Dict[str, List[PositionAnalysis]] = {}
    for a in analyses:
        key = f"{a.symbol}_{a.strategy}"
        grouped.setdefault(key, []).append(a)
        grouped.setdefault(f"{a.symbol}_ALL", []).append(a)
        grouped.setdefault(f"ALL_{a.strategy}", []).append(a)

    cache: Dict[str, DerivedExitParameters] = {}
    for key, group in grouped.items():
        params = derive_parameters_for_group(group)
        if params.is_valid:
            cache[key] = params

    # Global fallback using all available data
    global_params = derive_parameters_for_group(analyses, min_samples=1)
    # Note: if global_params.is_valid is False, we keep it as False. NO_VIABLE_POLICY support.
    cache["GLOBAL_FALLBACK"] = global_params
    return cache
