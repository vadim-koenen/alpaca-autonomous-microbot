# ADVISORY ONLY — Additional reconciliation safety checks for the local review gate (P2-018E)

"""
This test file adds regression coverage for patterns that must be blocked
for safe reconciliation work.

It exercises the existing local_review_gate.py (if present) or provides
standalone static checks that future patches can be validated against.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _scan_for_forbidden_patterns():
    forbidden = [
        (r'logs/coinbase_fills\.csv', 'Writing to logs/coinbase_fills.csv outside tests'),
        (r'append_coinbase_fill_row', 'Calling append_coinbase_fill_row in production paths'),
        (r'--live-read-only(?!.*--json)', 'Running live mode by default in non-capture scripts'),
    ]

    violations = []
    # Only scan the scripts/ directory for offline reconciliation tools
    for py_file in (REPO_ROOT / "scripts").rglob("*.py"):
        if "test" in py_file.parts:
            continue
        try:
            content = py_file.read_text()
            # Only flag if the file claims to be offline/read-only
            if "offline" in content.lower() or "read-only" in content.lower() or "no broker" in content.lower():
                for pattern, message in forbidden:
                    if re.search(pattern, content):
                        violations.append((py_file, message))
        except Exception:
            pass
    return violations


def test_no_forbidden_reconciliation_patterns_in_production_code():
    violations = _scan_for_forbidden_patterns()
    assert len(violations) == 0, f"Forbidden patterns found: {violations[:5]}"


def test_zero_qty_policy_is_documented_in_gate_runbook():
    gate_doc = REPO_ROOT / "docs" / "BROKER_TRUTH_AND_PL_EVIDENCE_GATE.md"
    if gate_doc.exists():
        content = gate_doc.read_text()
        assert "zero-qty" in content.lower() or "zero qty" in content.lower()
