#!/usr/bin/env python3
"""Ingest advisory crypto news/trend context into shadow learner tables."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shadow_learner.news_context import (
    DEFAULT_FEEDS,
    fetch_feed_items,
    read_manual_items,
    record_news_items,
    since_to_utc,
)


def _format_counts(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["  none"]
    return [f"  {key}: {counts[key]}" for key in sorted(counts)]


def build_output(summary: dict, *, dry_run: bool, fetch_errors: list[str]) -> str:
    lines = [
        "Shadow News Ingest",
        f"Mode: {'dry-run' if dry_run else 'write'}",
        f"Items seen: {summary['seen']}",
        f"Items after since: {summary['after_since']}",
        f"Inserted items: {summary['inserted']}",
        f"Existing items: {summary['existing']}",
        f"Inserted links: {summary['links_inserted']}",
        f"Existing links: {summary['links_existing']}",
        "",
        "Count by source:",
        *_format_counts(summary["by_source"]),
        "",
        "Count by symbol:",
        *_format_counts(summary["by_symbol"]),
        "",
        "Count by theme:",
        *_format_counts(summary["by_theme"]),
    ]
    if fetch_errors:
        lines.extend(["", "Feed fetch notes:"])
        lines.extend(f"  {error}" for error in fetch_errors)
    if summary["sample_titles"]:
        lines.extend(["", "Sample titles:"])
        lines.extend(f"  {title}" for title in summary["sample_titles"])
    lines.extend(["", "Recommendation: advisory only; not used for live trading"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None, help="UTC date or timestamp lower bound")
    parser.add_argument("--input-file", default=None, help="Manual JSON/text import path")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    parser.add_argument("--feed-limit", type=int, default=25)
    parser.add_argument("--timeout-seconds", type=float, default=3.0)
    parser.add_argument("--skip-fetch", action="store_true", help="Use manual input only")
    args = parser.parse_args()

    since_utc = since_to_utc(args.since)
    items = []
    fetch_errors: list[str] = []
    if args.input_file:
        items.extend(read_manual_items(args.input_file))
    if not args.skip_fetch:
        for source, url in DEFAULT_FEEDS.items():
            fetched, error = fetch_feed_items(
                source,
                url,
                timeout_seconds=args.timeout_seconds,
                limit=args.feed_limit,
            )
            items.extend(fetched)
            if error:
                fetch_errors.append(error)

    summary = record_news_items(
        items,
        db_path=args.db,
        since_utc=since_utc,
        dry_run=args.dry_run,
    )
    print(build_output(summary, dry_run=args.dry_run, fetch_errors=fetch_errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
