"""Advisory news context ingestion helpers."""

from __future__ import annotations

import email.utils
import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.redact import redact_text

from .news_classifier import classify_news
from .schema import connect, init_db, json_dumps, utc_now

DEFAULT_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "The Block": "https://www.theblock.co/rss.xml",
    "Unchained": "https://unchainedcrypto.com/feed/",
    "Coinbase Blog": "https://www.coinbase.com/blog/rss",
}

SOURCE_RELIABILITY = {
    "CoinDesk": 0.80,
    "The Block": 0.78,
    "Unchained": 0.74,
    "Coinbase Blog": 0.72,
    "Coinbase Market Briefing": 0.70,
    "manual": 0.60,
}


@dataclass(frozen=True)
class NewsInput:
    source: str
    title: str
    summary: str = ""
    published_at_utc: str = ""
    source_url: str = ""
    payload: dict[str, Any] | None = None


def redact_news_text(text: str) -> str:
    return redact_text(text or "")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_title(title: str) -> str:
    return " ".join(title.lower().strip().split())


def _parse_datetime(value: str | None) -> str:
    if not value:
        return utc_now()
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return utc_now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_since(published_at_utc: str, since_utc: str | None) -> bool:
    if not since_utc:
        return True
    return published_at_utc >= since_utc


def since_to_utc(value: str | None) -> str | None:
    if not value:
        return None
    if "T" in value:
        return _parse_datetime(value)
    parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def stable_news_id(source: str, title: str, raw_text_hash: str) -> str:
    return "news_" + _hash_text(f"{source}|{_normalize_title(title)}|{raw_text_hash}")[:32]


def stable_link_id(news_id: str, symbol: str, theme: str) -> str:
    return "nlink_" + _hash_text(f"{news_id}|{symbol}|{theme}")[:32]


def duplicate_group_id(title: str) -> str:
    return "dup_" + _hash_text(_normalize_title(title))[:32]


def read_manual_items(path: str | Path) -> list[NewsInput]:
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        jsonl_items = _read_jsonl_items(stripped)
        if jsonl_items:
            return jsonl_items
        return _read_text_blocks(stripped)
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []
    items = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        items.append(
            NewsInput(
                source=str(item.get("source") or "manual"),
                source_url=str(item.get("source_url") or ""),
                title=title,
                summary=str(item.get("summary") or ""),
                published_at_utc=_parse_datetime(str(item.get("published_at_utc") or "")),
                payload={key: value for key, value in item.items() if key not in {"title", "summary"}},
            )
        )
    return items


def _read_jsonl_items(text: str) -> list[NewsInput]:
    items: list[NewsInput] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            return []
        if not isinstance(item, dict):
            return []
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        items.append(
            NewsInput(
                source=str(item.get("source") or "manual"),
                source_url=str(item.get("source_url") or ""),
                title=title,
                summary=str(item.get("summary") or ""),
                published_at_utc=_parse_datetime(str(item.get("published_at_utc") or "")),
                payload={key: value for key, value in item.items() if key not in {"title", "summary"}},
            )
        )
    return items


def _read_text_blocks(text: str) -> list[NewsInput]:
    items = []
    for block in [part.strip() for part in text.split("\n\n") if part.strip()]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        items.append(
            NewsInput(
                source="manual",
                title=lines[0],
                summary=" ".join(lines[1:]),
                published_at_utc=utc_now(),
            )
        )
    return items


def fetch_feed_items(
    source: str,
    url: str,
    *,
    timeout_seconds: float = 3.0,
    limit: int = 25,
) -> tuple[list[NewsInput], str]:
    """Fetch one RSS/Atom feed with stdlib only. Failures are returned, not raised."""
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "shadow-learner-news-context/1.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(1_000_000)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [], f"{source}: {type(exc).__name__}"
    return parse_feed_bytes(source, url, payload, limit=limit), ""


def parse_feed_bytes(source: str, feed_url: str, payload: bytes, *, limit: int = 25) -> list[NewsInput]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    items: list[NewsInput] = []
    channel_items = root.findall(".//item")
    if channel_items:
        for item in channel_items[:limit]:
            title = _node_text(item, "title")
            if not title:
                continue
            items.append(
                NewsInput(
                    source=source,
                    source_url=_node_text(item, "link") or feed_url,
                    title=title,
                    summary=_node_text(item, "description"),
                    published_at_utc=_parse_datetime(_node_text(item, "pubDate")),
                    payload={"feed_url": feed_url},
                )
            )
        return items
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns)[:limit]:
        title = _node_text(entry, "atom:title", ns)
        link = ""
        link_node = entry.find("atom:link", ns)
        if link_node is not None:
            link = link_node.attrib.get("href", "")
        items.append(
            NewsInput(
                source=source,
                source_url=link or feed_url,
                title=title,
                summary=_node_text(entry, "atom:summary", ns),
                published_at_utc=_parse_datetime(_node_text(entry, "atom:updated", ns)),
                payload={"feed_url": feed_url},
            )
        )
    return [item for item in items if item.title]


def _node_text(node: ET.Element, path: str, ns: dict[str, str] | None = None) -> str:
    found = node.find(path, ns or {})
    if found is None or found.text is None:
        return ""
    return " ".join(found.text.strip().split())


def record_news_items(
    items: Iterable[NewsInput],
    *,
    db_path: str | Path | None = None,
    since_utc: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "seen": 0,
        "after_since": 0,
        "inserted": 0,
        "existing": 0,
        "links_inserted": 0,
        "links_existing": 0,
        "by_source": {},
        "by_theme": {},
        "by_symbol": {},
        "sample_titles": [],
    }
    if not dry_run:
        init_db(db_path)
    for item in items:
        summary["seen"] += 1
        published_at = _parse_datetime(item.published_at_utc)
        if not _is_since(published_at, since_utc):
            continue
        summary["after_since"] += 1
        stored_title = redact_news_text(item.title)
        stored_summary = redact_news_text(item.summary)
        stored_url = redact_news_text(item.source_url)
        raw_text_hash = _hash_text(f"{stored_title}\n{stored_summary}")
        news_id = stable_news_id(item.source, stored_title, raw_text_hash)
        classification = classify_news(stored_title, stored_summary)
        for source_map, key in (
            (summary["by_source"], item.source),
        ):
            source_map[key] = source_map.get(key, 0) + 1
        for theme in classification["themes"]:
            summary["by_theme"][theme] = summary["by_theme"].get(theme, 0) + 1
        for symbol in classification["symbols"]:
            summary["by_symbol"][symbol] = summary["by_symbol"].get(symbol, 0) + 1
        if len(summary["sample_titles"]) < 5:
            summary["sample_titles"].append(stored_title)
        if dry_run:
            continue
        existing = _news_exists(news_id, item.source, raw_text_hash, db_path)
        if existing:
            summary["existing"] += 1
        else:
            summary["inserted"] += 1
        _insert_news_item(
            db_path=db_path,
            news_id=news_id,
            item=item,
            title=stored_title,
            summary=stored_summary,
            source_url=stored_url,
            published_at_utc=published_at,
            raw_text_hash=raw_text_hash,
            classification=classification,
        )
        for symbol in classification["symbols"] or [""]:
            if not symbol:
                continue
            for theme in classification["themes"]:
                link_id = stable_link_id(news_id, symbol, theme)
                existed = _link_exists(link_id, db_path)
                if existed:
                    summary["links_existing"] += 1
                else:
                    summary["links_inserted"] += 1
                _insert_link(
                    db_path=db_path,
                    link_id=link_id,
                    news_id=news_id,
                    symbol=symbol,
                    theme=theme,
                    classification=classification,
                )
    return summary


def _news_exists(news_id: str, source: str, raw_text_hash: str, db_path: str | Path | None) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM shadow_news_items
            WHERE news_id = ? OR (source = ? AND raw_text_hash = ?)
            """,
            (news_id, source, raw_text_hash),
        ).fetchone()
    return row is not None


def _link_exists(link_id: str, db_path: str | Path | None) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM shadow_news_signal_links WHERE link_id = ?",
            (link_id,),
        ).fetchone()
    return row is not None


def _insert_news_item(
    *,
    db_path: str | Path | None,
    news_id: str,
    item: NewsInput,
    title: str,
    summary: str,
    source_url: str,
    published_at_utc: str,
    raw_text_hash: str,
    classification: dict[str, Any],
) -> None:
    reliability = SOURCE_RELIABILITY.get(item.source, SOURCE_RELIABILITY["manual"])
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO shadow_news_items (
                news_id, source, source_url, title, summary, published_at_utc,
                ingested_at_utc, raw_text_hash, symbols_json, sectors_json,
                themes_json, sentiment_score, impact_score, time_horizon,
                source_reliability, duplicate_group_id, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                news_id,
                item.source,
                source_url,
                title,
                summary,
                published_at_utc,
                utc_now(),
                raw_text_hash,
                json_dumps(classification["symbols"]),
                json_dumps(classification["sectors"]),
                json_dumps(classification["themes"]),
                classification["sentiment_score"],
                classification["impact_score"],
                classification["time_horizon"],
                reliability,
                duplicate_group_id(title),
                json_dumps(
                    {
                        "classifier": "deterministic_keywords_v0",
                        "direction_hint": classification["direction_hint"],
                        "confidence": classification["confidence"],
                        "input_payload": item.payload or {},
                    }
                ),
            ),
        )


def _insert_link(
    *,
    db_path: str | Path | None,
    link_id: str,
    news_id: str,
    symbol: str,
    theme: str,
    classification: dict[str, Any],
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO shadow_news_signal_links (
                link_id, news_id, symbol, asset_class, theme, direction_hint,
                confidence, reason_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link_id,
                news_id,
                symbol,
                "crypto",
                theme,
                classification["direction_hint"],
                classification["confidence"],
                json_dumps({"sentiment_score": classification["sentiment_score"], "impact_score": classification["impact_score"]}),
                utc_now(),
            ),
        )


def count_news_rows(db_path: str | Path | None = None) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM shadow_news_items").fetchone()[0])


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
