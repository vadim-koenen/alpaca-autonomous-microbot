# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Coinbase Price-Path MFE/MAE Analyzer — P2-005

Reads logs/coinbase_price_path.csv and prints an advisory stdout report.
Class 1: no live trading behavior changes.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = REPO_ROOT / "logs" / "coinbase_price_path.csv"
OPTIONAL_JOURNAL_PATH = REPO_ROOT / "journal_coinbase_crypto.csv"

THRESHOLDS_PCT = (0.60, 1.20, 1.50, 2.00, 2.40)
MIN_POSITION_PATHS = 20
MIN_DATA_SPAN_DAYS = 14  # conservative: 2 weeks; Class 2 needs ~2–3 weeks

FIELDNAMES = (
    "timestamp_utc",
    "symbol",
    "position_id",
    "entry_price",
    "current_price",
    "unrealized_pct",
    "hold_minutes",
    "entry_timestamp",
)


@dataclass(frozen=True)
class PositionKey:
    position_id: str
    symbol: str
    entry_timestamp: str


@dataclass
class ThresholdCrossing:
    threshold_pct: float
    crossed: bool
    first_timestamp_utc: Optional[str] = None
    first_hold_minutes: Optional[float] = None


@dataclass
class PositionAnalysis:
    key: PositionKey
    sample_count: int
    first_sample_timestamp_utc: Optional[str]
    last_sample_timestamp_utc: Optional[str]
    entry_price: Optional[float]
    latest_current_price: Optional[float]
    latest_unrealized_pct: Optional[float]
    mfe_pct: Optional[float]
    mae_pct: Optional[float]
    latest_hold_minutes: Optional[float]
    max_hold_minutes: Optional[float]
    threshold_crossings: list[ThresholdCrossing] = field(default_factory=list)
    fallback_below_120_after_cross_120: Optional[bool] = None
    fallback_below_120_after_cross_150: Optional[bool] = None


@dataclass
class SymbolSummary:
    symbol: str
    positions_observed: int
    total_samples: int
    average_mfe_pct: Optional[float]
    max_mfe_pct: Optional[float]
    average_mae_pct: Optional[float]
    min_mae_pct: Optional[float]
    pct_crossed_120: float
    pct_crossed_240: float


def parse_iso_timestamp(ts_str: str) -> Optional[datetime]:
    if not ts_str or not str(ts_str).strip():
        return None
    try:
        normalized = str(ts_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_price_path_csv(path: Path) -> tuple[list[dict[str, str]], Optional[str]]:
    """
    Read CSV rows. Returns (rows, error_message).
    error_message is set when file is missing; empty list when file exists but has no data rows.
    """
    if not path.exists():
        return [], f"CSV not found: {path}"

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return [], None
            rows = [row for row in reader if any((v or "").strip() for v in row.values())]
            return rows, None
    except OSError as exc:
        return [], f"Could not read CSV: {exc}"


def position_key_from_row(row: dict[str, str]) -> Optional[PositionKey]:
    position_id = (row.get("position_id") or "").strip()
    symbol = (row.get("symbol") or "").strip()
    entry_timestamp = (row.get("entry_timestamp") or "").strip()
    if not position_id or not symbol or not entry_timestamp:
        return None
    return PositionKey(position_id, symbol, entry_timestamp)


def group_rows_by_position(rows: list[dict[str, str]]) -> dict[PositionKey, list[dict[str, str]]]:
    grouped: dict[PositionKey, list[dict[str, str]]] = {}
    for row in rows:
        key = position_key_from_row(row)
        if key is None:
            continue
        grouped.setdefault(key, []).append(row)

    for key in grouped:
        grouped[key].sort(
            key=lambda r: (
                parse_iso_timestamp(r.get("timestamp_utc", "")) or datetime.min.replace(tzinfo=timezone.utc),
                r.get("timestamp_utc", ""),
            )
        )
    return grouped


def detect_threshold_crossings(
    samples: list[dict[str, str]],
    thresholds: tuple[float, ...] = THRESHOLDS_PCT,
) -> list[ThresholdCrossing]:
    crossings: list[ThresholdCrossing] = []
    for threshold in thresholds:
        first_ts: Optional[str] = None
        first_hold: Optional[float] = None
        crossed = False
        for row in samples:
            unrealized = safe_float(row.get("unrealized_pct"))
            if unrealized is None:
                continue
            if unrealized >= threshold:
                crossed = True
                first_ts = (row.get("timestamp_utc") or "").strip() or None
                first_hold = safe_float(row.get("hold_minutes"))
                break
        crossings.append(
            ThresholdCrossing(
                threshold_pct=threshold,
                crossed=crossed,
                first_timestamp_utc=first_ts,
                first_hold_minutes=first_hold,
            )
        )
    return crossings


def analyze_position(key: PositionKey, samples: list[dict[str, str]]) -> PositionAnalysis:
    unrealized_values: list[float] = []
    hold_values: list[float] = []
    entry_price: Optional[float] = None
    latest_row: Optional[dict[str, str]] = None

    for row in samples:
        if entry_price is None:
            entry_price = safe_float(row.get("entry_price"))
        u = safe_float(row.get("unrealized_pct"))
        if u is not None:
            unrealized_values.append(u)
        h = safe_float(row.get("hold_minutes"))
        if h is not None:
            hold_values.append(h)
        latest_row = row

    crossings = detect_threshold_crossings(samples)
    latest_unrealized = safe_float(latest_row.get("unrealized_pct")) if latest_row else None

    crossed_120 = any(c.threshold_pct == 1.20 and c.crossed for c in crossings)
    crossed_150 = any(c.threshold_pct == 1.50 and c.crossed for c in crossings)

    fallback_120: Optional[bool] = None
    if crossed_120 and latest_unrealized is not None:
        fallback_120 = latest_unrealized < 1.20

    fallback_150: Optional[bool] = None
    if crossed_150 and latest_unrealized is not None:
        fallback_150 = latest_unrealized < 1.20

    return PositionAnalysis(
        key=key,
        sample_count=len(samples),
        first_sample_timestamp_utc=(samples[0].get("timestamp_utc") or "").strip() or None if samples else None,
        last_sample_timestamp_utc=(samples[-1].get("timestamp_utc") or "").strip() or None if samples else None,
        entry_price=entry_price,
        latest_current_price=safe_float(latest_row.get("current_price")) if latest_row else None,
        latest_unrealized_pct=latest_unrealized,
        mfe_pct=max(unrealized_values) if unrealized_values else None,
        mae_pct=min(unrealized_values) if unrealized_values else None,
        latest_hold_minutes=safe_float(latest_row.get("hold_minutes")) if latest_row else None,
        max_hold_minutes=max(hold_values) if hold_values else None,
        threshold_crossings=crossings,
        fallback_below_120_after_cross_120=fallback_120,
        fallback_below_120_after_cross_150=fallback_150,
    )


def build_symbol_summaries(positions: list[PositionAnalysis]) -> list[SymbolSummary]:
    by_symbol: dict[str, list[PositionAnalysis]] = {}
    for pos in positions:
        by_symbol.setdefault(pos.key.symbol, []).append(pos)

    summaries: list[SymbolSummary] = []
    for symbol in sorted(by_symbol):
        items = by_symbol[symbol]
        mfes = [p.mfe_pct for p in items if p.mfe_pct is not None]
        maes = [p.mae_pct for p in items if p.mae_pct is not None]
        crossed_120 = sum(
            1 for p in items if any(c.threshold_pct == 1.20 and c.crossed for c in p.threshold_crossings)
        )
        crossed_240 = sum(
            1 for p in items if any(c.threshold_pct == 2.40 and c.crossed for c in p.threshold_crossings)
        )
        n = len(items)
        summaries.append(
            SymbolSummary(
                symbol=symbol,
                positions_observed=n,
                total_samples=sum(p.sample_count for p in items),
                average_mfe_pct=round(mean(mfes), 4) if mfes else None,
                max_mfe_pct=round(max(mfes), 4) if mfes else None,
                average_mae_pct=round(mean(maes), 4) if maes else None,
                min_mae_pct=round(min(maes), 4) if maes else None,
                pct_crossed_120=round(100.0 * crossed_120 / n, 1) if n else 0.0,
                pct_crossed_240=round(100.0 * crossed_240 / n, 1) if n else 0.0,
            )
        )
    return summaries


def data_span_days(positions: list[PositionAnalysis]) -> Optional[float]:
    timestamps: list[datetime] = []
    for pos in positions:
        for ts_str in (pos.first_sample_timestamp_utc, pos.last_sample_timestamp_utc):
            dt = parse_iso_timestamp(ts_str) if ts_str else None
            if dt:
                timestamps.append(dt)
    if len(timestamps) < 2:
        return None
    span = max(timestamps) - min(timestamps)
    return span.total_seconds() / 86400.0


def journal_available(path: Path = OPTIONAL_JOURNAL_PATH) -> bool:
    return path.exists() and path.stat().st_size > 0


def build_advisory_verdict(
    positions: list[PositionAnalysis],
    span_days: Optional[float],
) -> list[str]:
    lines: list[str] = []
    n = len(positions)
    enough_paths = n >= MIN_POSITION_PATHS
    enough_span = span_days is not None and span_days >= MIN_DATA_SPAN_DAYS

    lines.append(f"Position paths observed: {n} (minimum recommended: {MIN_POSITION_PATHS})")
    if span_days is not None:
        lines.append(f"Data span: {span_days:.1f} days (minimum recommended: {MIN_DATA_SPAN_DAYS}+ days / ~2–3 weeks)")
    else:
        lines.append("Data span: insufficient timestamps to compute")

    if not enough_paths:
        lines.append("VERDICT: Sample too small — fewer than 20 observed position paths.")
    if not enough_span:
        lines.append(
            "VERDICT: Class 2 SL/TP/hold-time tuning remains premature — fewer than 2 weeks of price-path data."
        )
    if enough_paths and enough_span:
        lines.append("VERDICT: Minimum path count and span thresholds met — review MFE/MAE tables before any Class 2 change.")

    crossed_maker_be = sum(
        1 for p in positions if any(c.threshold_pct == 0.60 and c.crossed for c in p.threshold_crossings)
    )
    fallback_after_be = sum(1 for p in positions if p.fallback_below_120_after_cross_120 is True)
    lines.append(
        f"Maker break-even (+0.60%) intra-hold: {crossed_maker_be}/{n} positions crossed at least once."
    )
    if n:
        lines.append(
            f"Fallback after +1.20%: {fallback_after_be}/{n} positions crossed +1.20% then latest < +1.20%."
        )

    if not enough_paths or not enough_span:
        lines.append("Class 2 TP/SL tuning: BLOCKED — collect more price-path samples first.")
    else:
        high_mfe = sum(1 for p in positions if p.mfe_pct is not None and p.mfe_pct >= 1.20)
        lines.append(
            f"Class 2 TP/SL tuning: ADVISORY ONLY — {high_mfe}/{n} paths reached MFE >= +1.20%; "
            "human review required before any live parameter change."
        )
    return lines


def format_report(
    csv_path: Path,
    rows: list[dict[str, str]],
    positions: list[PositionAnalysis],
    symbol_summaries: list[SymbolSummary],
    verdict_lines: list[str],
    read_error: Optional[str],
    journal_path: Path,
) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("COINBASE PRICE-PATH MFE/MAE REPORT (P2-005 — ADVISORY ONLY)")
    lines.append("=" * 72)
    lines.append(f"Source: {csv_path}")
    if read_error:
        lines.append(f"Status: {read_error}")
        lines.append("")
        lines.append("No position analysis — run P2-003 logger while positions are open.")
        return "\n".join(lines) + "\n"

    if not rows:
        lines.append("Status: CSV exists but contains no data rows.")
        lines.append("")
        lines.append("No position analysis — run P2-003 logger while positions are open.")
        return "\n".join(lines) + "\n"

    if journal_available(journal_path):
        lines.append(f"Optional context available (not used for matching): {journal_path.name}")
    else:
        lines.append("Optional journal: not present (analysis uses price-path CSV only).")
    lines.append(f"Raw rows: {len(rows)} | Position paths: {len(positions)}")
    lines.append("")

    if not positions:
        lines.append("No groupable position paths (need position_id, symbol, entry_timestamp on each row).")
        return "\n".join(lines) + "\n"

    lines.append("-" * 72)
    lines.append("PER-POSITION ANALYSIS")
    lines.append("-" * 72)
    for pos in sorted(positions, key=lambda p: (p.key.symbol, p.key.entry_timestamp)):
        lines.append("")
        lines.append(f"Position: {pos.key.position_id} | {pos.key.symbol} | entry={pos.key.entry_timestamp}")
        lines.append(f"  samples: {pos.sample_count}")
        lines.append(f"  first_sample: {pos.first_sample_timestamp_utc}")
        lines.append(f"  last_sample:  {pos.last_sample_timestamp_utc}")
        lines.append(f"  entry_price: {pos.entry_price}")
        lines.append(f"  latest current_price: {pos.latest_current_price}")
        lines.append(f"  latest unrealized_pct: {pos.latest_unrealized_pct}")
        lines.append(f"  MFE (max unrealized_pct): {pos.mfe_pct}")
        lines.append(f"  MAE (min unrealized_pct): {pos.mae_pct}")
        lines.append(f"  latest hold_minutes: {pos.latest_hold_minutes}")
        lines.append(f"  max hold_minutes: {pos.max_hold_minutes}")
        lines.append("  Threshold crossings:")
        for cross in pos.threshold_crossings:
            if cross.crossed:
                lines.append(
                    f"    +{cross.threshold_pct:.2f}%: YES @ {cross.first_timestamp_utc} "
                    f"(hold_minutes={cross.first_hold_minutes})"
                )
            else:
                lines.append(f"    +{cross.threshold_pct:.2f}%: no")
        if pos.fallback_below_120_after_cross_120 is not None:
            lines.append(
                f"  Fallback after +1.20% cross (latest < +1.20%): {pos.fallback_below_120_after_cross_120}"
            )
        if pos.fallback_below_120_after_cross_150 is not None:
            lines.append(
                f"  Fallback after +1.50% cross (latest < +1.20%): {pos.fallback_below_120_after_cross_150}"
            )

    lines.append("")
    lines.append("-" * 72)
    lines.append("BY-SYMBOL SUMMARY")
    lines.append("-" * 72)
    for summary in symbol_summaries:
        lines.append("")
        lines.append(f"Symbol: {summary.symbol}")
        lines.append(f"  positions_observed: {summary.positions_observed}")
        lines.append(f"  total_samples: {summary.total_samples}")
        lines.append(f"  average_MFE_pct: {summary.average_mfe_pct}")
        lines.append(f"  max_MFE_pct: {summary.max_mfe_pct}")
        lines.append(f"  average_MAE_pct: {summary.average_mae_pct}")
        lines.append(f"  min_MAE_pct: {summary.min_mae_pct}")
        lines.append(f"  pct_crossed_+1.20%: {summary.pct_crossed_120}%")
        lines.append(f"  pct_crossed_+2.40%: {summary.pct_crossed_240}%")

    lines.append("")
    lines.append("-" * 72)
    lines.append("ADVISORY VERDICT")
    lines.append("-" * 72)
    for line in verdict_lines:
        lines.append(line)
    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def run_analysis(csv_path: Path = DEFAULT_CSV_PATH) -> str:
    rows, read_error = read_price_path_csv(csv_path)
    if read_error:
        return format_report(csv_path, [], [], [], [], read_error, OPTIONAL_JOURNAL_PATH)

    grouped = group_rows_by_position(rows)
    positions = [analyze_position(key, samples) for key, samples in grouped.items()]
    symbol_summaries = build_symbol_summaries(positions)
    span = data_span_days(positions)
    verdict = build_advisory_verdict(positions, span)
    return format_report(
        csv_path, rows, positions, symbol_summaries, verdict, None, OPTIONAL_JOURNAL_PATH
    )


def main() -> None:
    csv_path = DEFAULT_CSV_PATH
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1]).expanduser().resolve()
    print(run_analysis(csv_path), end="")


if __name__ == "__main__":
    main()
