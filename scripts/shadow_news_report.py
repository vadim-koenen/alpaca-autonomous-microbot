#!/usr/bin/env python3
"""Report advisory crypto news/trend context stored by the shadow learner."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.news_context import since_to_utc
from shadow_learner.schema import connect, init_db


def _count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def build_report(*, db_path: str | Path | None, since: str | None) -> str:
    since_utc = since_to_utc(since)
    init_db(db_path)
    where = "WHERE published_at_utc >= ?" if since_utc else ""
    params = (since_utc,) if since_utc else ()
    with connect(db_path) as conn:
        total = _count(conn, f"SELECT COUNT(*) FROM shadow_news_items {where}", params)
        by_source = _rows(
            conn,
            f"""
            SELECT source, COUNT(*) AS count
            FROM shadow_news_items
            {where}
            GROUP BY source
            ORDER BY count DESC, source
            """,
            params,
        )
        rows = _rows(
            conn,
            f"""
            SELECT *
            FROM shadow_news_items
            {where}
            ORDER BY published_at_utc DESC, ingested_at_utc DESC
            """,
            params,
        )
        positive = _rows(
            conn,
            f"""
            SELECT title, source, sentiment_score, impact_score, symbols_json, themes_json
            FROM shadow_news_items
            {where}
            ORDER BY sentiment_score * impact_score DESC, impact_score DESC
            LIMIT 5
            """,
            params,
        )
        negative = _rows(
            conn,
            f"""
            SELECT title, source, sentiment_score, impact_score, symbols_json, themes_json
            FROM shadow_news_items
            {where}
            ORDER BY sentiment_score * impact_score ASC, impact_score DESC
            LIMIT 5
            """,
            params,
        )

    symbol_counts: Counter[str] = Counter()
    theme_counts: Counter[str] = Counter()
    unknown_items = 0
    for row in rows:
        symbols = _json_list(row["symbols_json"])
        themes = _json_list(row["themes_json"])
        symbol_counts.update(symbols)
        theme_counts.update(themes)
        if "unknown" in themes or not symbols:
            unknown_items += 1

    lines = [
        "Shadow News Report",
        f"Since: {since_utc or 'all'}",
        f"Total news items: {total}",
        "",
        "Count by source:",
    ]
    if by_source:
        lines.extend(f"  {row['source']}: {row['count']}" for row in by_source)
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Count by symbol:")
    if symbol_counts:
        lines.extend(f"  {symbol}: {count}" for symbol, count in symbol_counts.most_common(20))
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Count by theme:")
    if theme_counts:
        lines.extend(f"  {theme}: {count}" for theme, count in theme_counts.most_common(20))
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Top positive catalysts:")
    lines.extend(_format_catalysts(positive))

    lines.append("")
    lines.append("Top negative catalysts:")
    lines.extend(_format_catalysts(negative))

    lines.extend(
        [
            "",
            f"Unresolved/unknown items: {unknown_items}",
            "",
            "Recommendation: advisory only; not used for live trading",
        ]
    )
    return "\n".join(lines)


def _format_catalysts(rows: list[sqlite3.Row]) -> list[str]:
    if not rows:
        return ["  none"]
    lines = []
    for row in rows:
        symbols = ",".join(_json_list(row["symbols_json"])) or "no_symbol"
        themes = ",".join(_json_list(row["themes_json"])) or "unknown"
        title = redact_text(row["title"])
        lines.append(
            f"  {title} | {row['source']} | symbols={symbols} | themes={themes} "
            f"| sentiment={row['sentiment_score']:.2f} impact={row['impact_score']:.2f}"
        )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None, help="UTC date or timestamp lower bound")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    args = parser.parse_args()
    print(build_report(db_path=args.db, since=args.since))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
