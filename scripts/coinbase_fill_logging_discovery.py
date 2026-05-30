#!/usr/bin/env python3
"""Read-only Coinbase fill logging implementation discovery.

This script scans local repository source files to identify where Coinbase
order responses, fill/proceeds/fee fields, and journal writes may already exist.
It does not call external APIs, read .env files, place orders, mutate runtime
state, or change configuration.
"""

from __future__ import annotations

import argparse
import ast
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

KEYWORDS: tuple[str, ...] = (
    "Coinbase",
    "coinbase",
    "submit",
    "order",
    "filled",
    "fill",
    "fee",
    "proceeds",
    "journal",
    "client_order_id",
    "order_id",
    "product_id",
    "average_filled_price",
    "filled_size",
    "quote",
    "advanced",
    "broker",
    "position",
    "cycle",
)

TEXT_SUFFIXES: set[str] = {
    ".py",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
}

GENERATED_OR_VOLATILE_SKIP_PATHS: set[str] = {
    "docs/ACTIVE_HANDOFF.md",
    "docs/COINBASE_FILL_LOGGING_IMPLEMENTATION_DISCOVERY.md",
}

SKIP_DIRS: set[str] = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "state",
    "runtime",
    "logs",
    "launchd",
}

MAX_FILE_BYTES = 1_000_000


@dataclass(frozen=True)
class FileHit:
    path: str
    category: str
    matched_keywords: tuple[str, ...]
    keyword_counts: tuple[tuple[str, int], ...]
    line_count: int


@dataclass(frozen=True)
class FunctionHit:
    path: str
    name: str
    lineno: int
    category: str
    matched_keywords: tuple[str, ...]


@dataclass
class DiscoveryReport:
    root: Path
    scanned_files: list[str] = field(default_factory=list)
    skipped_paths: list[str] = field(default_factory=list)
    file_hits: list[FileHit] = field(default_factory=list)
    function_hits: list[FunctionHit] = field(default_factory=list)
    keyword_totals: Counter[str] = field(default_factory=Counter)

    @property
    def candidate_categories(self) -> Counter[str]:
        return Counter(hit.category for hit in self.file_hits)


def _is_secret_or_env(path: Path) -> bool:
    name = path.name.lower()
    return name == ".env" or name.startswith(".env.") or name.endswith(".pem") or name.endswith(".key")


def _should_skip(path: Path, root: Path) -> bool:
    if _is_secret_or_env(path):
        return True
    try:
        rel = path.relative_to(root)
        rel_parts = rel.parts
        rel_posix = rel.as_posix()
    except ValueError:
        rel_parts = path.parts
        rel_posix = path.as_posix()

    if rel_posix in GENERATED_OR_VOLATILE_SKIP_PATHS:
        return True

    return any(part in SKIP_DIRS for part in rel_parts)


def _is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def classify_path(path: str) -> str:
    lowered = path.lower()
    if lowered.startswith(("docs/", "scripts/", "tests/")):
        return "read-only/reporting"
    if lowered.startswith(("state/", "runtime/", "logs/", "launchd/")):
        return "runtime/state path"
    if "journal" in lowered or "log" in lowered:
        return "journal/logging"
    if lowered.startswith("config") or "/config" in lowered or lowered.endswith((".yaml", ".yml", ".toml", ".ini", ".cfg")):
        return "config/risk path"
    execution_markers = (
        "broker",
        "order_manager",
        "risk_manager",
        "main.py",
        "strategy_crypto",
        "coinbase",
        "execution",
        "trade",
    )
    if any(marker in lowered for marker in execution_markers):
        return "broker/execution path"
    return "other/local source"


def _keyword_counts(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for keyword in KEYWORDS:
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        count = len(pattern.findall(text))
        if count:
            counts[keyword] = count
    return counts


def _safe_read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _function_hits(path: Path, rel: str, text: str, category: str) -> list[FunctionHit]:
    if path.suffix.lower() != ".py":
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = text.splitlines()
    hits: list[FunctionHit] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue

        start = max(getattr(node, "lineno", 1) - 1, 0)
        end = getattr(node, "end_lineno", None)
        if end is None:
            end = min(start + 80, len(lines))
        block = "\n".join(lines[start:end])
        counts = _keyword_counts(node.name + "\n" + block)
        if counts:
            hits.append(
                FunctionHit(
                    path=rel,
                    name=node.name,
                    lineno=getattr(node, "lineno", 1),
                    category=category,
                    matched_keywords=tuple(sorted(counts)),
                )
            )

    return hits


def iter_candidate_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if _should_skip(path, root):
            continue
        if not _is_text_candidate(path):
            continue
        yield path


def discover_repository(root: str | Path) -> DiscoveryReport:
    repo_root = Path(root).resolve()
    report = DiscoveryReport(root=repo_root)

    for path in sorted(repo_root.rglob("*")):
        if path.is_dir():
            continue
        if _should_skip(path, repo_root):
            try:
                report.skipped_paths.append(path.relative_to(repo_root).as_posix())
            except ValueError:
                report.skipped_paths.append(path.as_posix())

    for path in iter_candidate_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        text = _safe_read(path)
        if text is None:
            report.skipped_paths.append(rel)
            continue

        report.scanned_files.append(rel)
        counts = _keyword_counts(text)
        if not counts:
            continue

        category = classify_path(rel)
        report.keyword_totals.update(counts)
        report.file_hits.append(
            FileHit(
                path=rel,
                category=category,
                matched_keywords=tuple(sorted(counts)),
                keyword_counts=tuple(sorted(counts.items())),
                line_count=len(text.splitlines()),
            )
        )
        report.function_hits.extend(_function_hits(path, rel, text, category))

    report.file_hits.sort(
        key=lambda hit: (
            -sum(count for _, count in hit.keyword_counts),
            hit.category,
            hit.path,
        )
    )
    report.function_hits.sort(key=lambda hit: (hit.path, hit.lineno, hit.name))
    report.skipped_paths = sorted(set(report.skipped_paths))
    report.scanned_files = sorted(set(report.scanned_files))
    return report


def _markdown_table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> str:
    if not rows:
        return "_None found._\n"

    escaped_headers = [header.replace("|", "\\|") for header in headers]
    out = [
        "| " + " | ".join(escaped_headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]

    for row in rows:
        escaped_row = [cell.replace("\n", " ").replace("|", "\\|") for cell in row]
        out.append("| " + " | ".join(escaped_row) + " |")

    return "\n".join(out) + "\n"


def render_markdown(report: DiscoveryReport) -> str:
    category_rows = [
        (category, str(count))
        for category, count in sorted(report.candidate_categories.items())
    ]

    file_rows = [
        (
            hit.path,
            hit.category,
            ", ".join(hit.matched_keywords),
            str(sum(count for _, count in hit.keyword_counts)),
        )
        for hit in report.file_hits[:80]
    ]

    function_rows = [
        (
            hit.path,
            str(hit.lineno),
            hit.name,
            hit.category,
            ", ".join(hit.matched_keywords),
        )
        for hit in report.function_hits[:120]
    ]

    keyword_rows = [
        (keyword, str(count))
        for keyword, count in sorted(report.keyword_totals.items(), key=lambda item: (-item[1], item[0]))
    ]

    skipped_preview = "\n".join(f"- `{path}`" for path in report.skipped_paths[:80]) or "_None._"

    recommended_next = (
        "Discovery only. Use the candidate map below to identify the narrowest append-only seam. "
        "The next implementation patch should prefer writing a new immutable fill/proceeds/fee row after a confirmed order/fill response is available, "
        "without changing sizing, strategy, risk caps, order submission, runtime state, or configuration."
    )

    return "\n".join(
        [
            "# Coinbase Fill Logging Implementation Discovery",
            "",
            "## Scope",
            "",
            "Class 1 / read-only discovery for locating Coinbase order/fill/journal seams in the local repository.",
            "",
            "This document is generated by `scripts/coinbase_fill_logging_discovery.py` and is intentionally limited to discovery. It does not authorize implementation, tuning, live trading changes, config edits, state edits, broker edits, or strategy edits.",
            "",
            "## Safety constraints",
            "",
            "- Does not call Coinbase APIs.",
            "- Does not read `.env`, `.env.*`, key, or pem files.",
            "- Skips `state/`, `runtime/`, `logs/`, and `launchd/` contents.",
            "- Does not place, cancel, or modify orders.",
            "- Does not change risk caps, strategy logic, config, broker/order code, or runtime state.",
            "",
            "## Summary",
            "",
            f"- Repository root scanned: `{report.root}`",
            f"- Text files scanned: `{len(report.scanned_files)}`",
            f"- Candidate files with Coinbase/order/fill/journal/proceeds/fee keywords: `{len(report.file_hits)}`",
            f"- Candidate Python functions/classes: `{len(report.function_hits)}`",
            "",
            "## Candidate categories",
            "",
            _markdown_table(category_rows, ("Category", "Candidate file count")),
            "## Candidate files",
            "",
            _markdown_table(file_rows, ("Path", "Risk classification", "Matched keywords", "Keyword hits")),
            "## Candidate Python functions/classes",
            "",
            _markdown_table(function_rows, ("Path", "Line", "Function/Class", "Risk classification", "Matched keywords")),
            "## Keyword totals",
            "",
            _markdown_table(keyword_rows, ("Keyword", "Total hits")),
            "## Skipped paths preview",
            "",
            skipped_preview,
            "",
            "## P2-010 recommendation",
            "",
            recommended_next,
            "",
            "## Implementation gate",
            "",
            "Do not implement fill logging until this discovery output is reviewed and the safest append-only hook is selected for P2-011 or later with explicit approval.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Coinbase fill logging discovery.")
    parser.add_argument("--repo", default=".", help="Repository root to scan.")
    parser.add_argument("--write-md", help="Optional markdown output path.")
    args = parser.parse_args()

    report = discover_repository(args.repo)
    markdown = render_markdown(report)

    if args.write_md:
        output_path = Path(args.write_md)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"Wrote discovery report: {output_path}")

    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
