#!/usr/bin/env python3
"""Import manual/read-only price history into the shadow learner DB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.price_history import PricePoint, read_price_file, record_price_points
from shadow_learner.schema import connect, resolve_db_path


def _format_counts(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["  none"]
    return [f"  {key}: {counts[key]}" for key in sorted(counts)]


def _shadow_symbols(db_path: str | None) -> set[str] | None:
    db_file = resolve_db_path(db_path)
    if not db_file.exists():
        return None
    try:
        with connect(db_file) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT symbol FROM shadow_predictions
                UNION
                SELECT DISTINCT symbol FROM shadow_feature_snapshots
                """
            ).fetchall()
    except Exception:
        return None
    return {str(row["symbol"]).upper() for row in rows if row["symbol"]}


def _filter_to_shadow_symbols(
    points: list[PricePoint],
    *,
    db_path: str | None,
) -> tuple[list[PricePoint], int]:
    symbols = _shadow_symbols(db_path)
    if symbols is None:
        return points, 0
    filtered = [point for point in points if point.symbol.upper() in symbols]
    return filtered, len(points) - len(filtered)


def build_output(summary: dict, errors: list[str], *, dry_run: bool, skipped_non_shadow: int = 0) -> str:
    lines = [
        "Shadow Price Import",
        f"Mode: {'dry-run' if dry_run else 'write'}",
        f"Rows seen: {summary['seen']}",
        f"Inserted price points: {summary['inserted']}",
        f"Existing price points: {summary['existing']}",
        f"Invalid rows: {len(errors)}",
        f"Skipped non-shadow symbols: {skipped_non_shadow}",
        "",
        "Count by source:",
        *_format_counts(summary["by_source"]),
        "",
        "Count by symbol:",
        *_format_counts(summary["by_symbol"]),
        "",
        "Count by timeframe:",
        *_format_counts(summary["by_timeframe"]),
    ]
    if errors:
        lines.extend(["", "Invalid row notes:"])
        lines.extend(f"  {redact_text(error)}" for error in errors[:10])
    lines.extend(["", "Recommendation: advisory only; not used for live trading"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", required=True, help="JSON/JSONL/CSV price file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    args = parser.parse_args()

    points, errors = read_price_file(args.input_file)
    points, skipped_non_shadow = _filter_to_shadow_symbols(points, db_path=args.db)
    summary = record_price_points(points, db_path=args.db, dry_run=args.dry_run)
    print(redact_text(build_output(summary, errors, dry_run=args.dry_run, skipped_non_shadow=skipped_non_shadow)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
