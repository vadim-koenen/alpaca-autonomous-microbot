#!/usr/bin/env python3
"""
ADVISORY ONLY — Open-source bot plumbing reference checker.

Read-only documentation validator for P2-009. This script does not fetch
internet resources, install packages, call broker APIs, read .env, place
orders, modify config/state/runtime, or affect live trading behavior.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

DEFAULT_DOC = Path("docs/OPEN_SOURCE_BOT_PLUMBING_SURVEY.md")

REQUIRED_PROJECTS: Tuple[str, ...] = (
    "Freqtrade",
    "Hummingbot",
    "Jesse",
    "OctoBot",
    "CCXT",
)

REQUIRED_PATTERNS: Tuple[str, ...] = (
    "Fill event is the source of truth",
    "Immutable fill ledger",
    "Stable cycle ID",
    "Exchange connector boundary",
    "Fee-aware realized P/L",
    "Paper/backtest/live parity",
    "Reconciliation before tuning",
)

REQUIRED_SAFETY_PHRASES: Tuple[str, ...] = (
    "Class 1",
    "does not copy external code",
    "Do not install or migrate",
    "Do not copy GPL code",
    "Do not copy public strategy logic",
    "Do not change live bot behavior",
    "Do not tune notional",
)

REQUIRED_NEXT_PATCHES: Tuple[str, ...] = (
    "P2-010",
    "P2-011",
    "P2-012",
)


@dataclass(frozen=True)
class ReferenceCheckResult:
    status: str
    path: Path
    missing_projects: Tuple[str, ...]
    missing_patterns: Tuple[str, ...]
    missing_safety_phrases: Tuple[str, ...]
    missing_next_patches: Tuple[str, ...]
    warnings: Tuple[str, ...]
    errors: Tuple[str, ...]


def read_doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def missing_terms(text: str, terms: Sequence[str]) -> Tuple[str, ...]:
    lowered = text.lower()
    return tuple(term for term in terms if term.lower() not in lowered)


def validate_reference_doc(path: Path) -> ReferenceCheckResult:
    path = path.resolve()

    if not path.exists():
        return ReferenceCheckResult(
            status="FAIL",
            path=path,
            missing_projects=REQUIRED_PROJECTS,
            missing_patterns=REQUIRED_PATTERNS,
            missing_safety_phrases=REQUIRED_SAFETY_PHRASES,
            missing_next_patches=REQUIRED_NEXT_PATCHES,
            warnings=tuple(),
            errors=("Reference survey document is missing.",),
        )

    text = read_doc(path)

    missing_projects = missing_terms(text, REQUIRED_PROJECTS)
    missing_patterns = missing_terms(text, REQUIRED_PATTERNS)
    missing_safety = missing_terms(text, REQUIRED_SAFETY_PHRASES)
    missing_next = missing_terms(text, REQUIRED_NEXT_PATCHES)

    errors: List[str] = []
    warnings: List[str] = []

    if missing_projects:
        errors.append("Missing reference projects: " + ", ".join(missing_projects))
    if missing_patterns:
        errors.append("Missing required plumbing patterns: " + ", ".join(missing_patterns))
    if missing_safety:
        errors.append("Missing safety phrases: " + ", ".join(missing_safety))
    if missing_next:
        errors.append("Missing next-patch sequence: " + ", ".join(missing_next))

    if "copy code" in text.lower() and "Do not copy" not in text:
        warnings.append("Document discusses copying code without an explicit do-not-copy guardrail.")

    status = "FAIL" if errors else "PASS"

    return ReferenceCheckResult(
        status=status,
        path=path,
        missing_projects=missing_projects,
        missing_patterns=missing_patterns,
        missing_safety_phrases=missing_safety,
        missing_next_patches=missing_next,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def render(result: ReferenceCheckResult) -> str:
    lines: List[str] = []
    lines.append("=== Open-Source Bot Plumbing Reference Check ===")
    lines.append("ADVISORY ONLY / READ ONLY / DOCUMENTATION VALIDATION ONLY")
    lines.append(f"Path: {result.path}")
    lines.append(f"Status: {result.status}")
    lines.append("")

    lines.append("--- Required projects ---")
    for project in REQUIRED_PROJECTS:
        marker = "MISSING" if project in result.missing_projects else "OK"
        lines.append(f"{marker:7} {project}")
    lines.append("")

    lines.append("--- Required plumbing patterns ---")
    for pattern in REQUIRED_PATTERNS:
        marker = "MISSING" if pattern in result.missing_patterns else "OK"
        lines.append(f"{marker:7} {pattern}")
    lines.append("")

    lines.append("--- Required safety phrases ---")
    for phrase in REQUIRED_SAFETY_PHRASES:
        marker = "MISSING" if phrase in result.missing_safety_phrases else "OK"
        lines.append(f"{marker:7} {phrase}")
    lines.append("")

    lines.append("--- Required next patches ---")
    for patch in REQUIRED_NEXT_PATCHES:
        marker = "MISSING" if patch in result.missing_next_patches else "OK"
        lines.append(f"{marker:7} {patch}")
    lines.append("")

    if result.warnings:
        lines.append("--- Warnings ---")
        for warning in result.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    if result.errors:
        lines.append("--- Errors ---")
        for error in result.errors:
            lines.append(f"- {error}")
        lines.append("")

    if result.status == "PASS":
        lines.append("Verdict: Reference survey satisfies the minimum P2-009 planning contract.")
    else:
        lines.append("Verdict: Reference survey is incomplete. Do not treat public-bot plumbing as integrated yet.")

    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Advisory-only open-source bot plumbing reference checker")
    parser.add_argument("--path", default=str(DEFAULT_DOC), help="Reference survey markdown path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on FAIL")
    args = parser.parse_args(argv)

    result = validate_reference_doc(Path(args.path))
    print(render(result), end="")

    if args.strict and result.status == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
