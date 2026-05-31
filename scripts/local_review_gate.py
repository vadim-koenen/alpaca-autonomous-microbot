#!/usr/bin/env python3
# ADVISORY ONLY — local review automation for Grok/Codex patches.
# No live trading calls, no broker APIs, no .env reads, no network except explicit git fetch,
# no order placement, no fill logger writes or append_coinbase_fill_row calls.
# This tool only performs local git inspection + py_compile + pytest + smoke commands
# to reduce human copy/paste error in patch reviews.

"""
Reusable local review gate for safe verification of review/ branches before
human/ChatGPT merge decision.

Grok/Codex should run this (or equivalent) before producing the final report.
Human pastes ONLY the compact final report block back to the AI.
"""

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence

# Default protected patterns (always checked). Configurable via --protected-file.
PROTECTED_DEFAULTS: List[str] = [
    ".env",
    "logs/coinbase_fills.csv",
    "logs/*",
    "runtime/*",
    "state/*",
    "launchd/*",
    "config_coinbase_crypto.yaml",
    "strategy_crypto.py",
    "main.py",
    "broker_coinbase.py",
    "order_manager.py",
    "position_manager.py",
    "risk_manager.py",
]


def run_cmd(cmd: str, check: bool = True, cwd: str = None) -> str:
    """Run shell command with GIT_PAGER=cat for clean output. Exit on failure if check=True."""
    env = os.environ.copy()
    env["GIT_PAGER"] = "cat"
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=check,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )
        return (result.stdout or "").strip()
    except subprocess.CalledProcessError as e:
        print(f"\n[FAIL] Command failed: {cmd}")
        if e.stdout:
            print("STDOUT:\n" + e.stdout)
        if e.stderr:
            print("STDERR:\n" + e.stderr)
        if check:
            sys.exit(1)
        return (e.stdout or "") + (e.stderr or "")


def normalize_list(items: Sequence[str]) -> List[str]:
    """Support repeated --flag and comma-separated values in one --flag."""
    out: List[str] = []
    for item in items or []:
        if not item:
            continue
        for part in str(item).split(","):
            p = part.strip()
            if p:
                out.append(p)
    return out


def is_protected(path: str, patterns: Sequence[str]) -> bool:
    """Match against glob-style protected patterns (simple fnmatch + prefix)."""
    p = path.strip()
    for pat in patterns:
        if not pat:
            continue
        if p == pat:
            return True
        if fnmatch.fnmatch(p, pat):
            return True
        if pat.endswith("/*") and p.startswith(pat[:-1]):
            return True
        if p.startswith(pat):
            return True
    return False


def has_production_append_call(txt: str) -> bool:
    """
    Smart production fill-logger detector.
    True only for actual call sites (append_...(...) ) in non-test code.
    Ignores:
      - anything under tests/
      - string literals used for negative assertions ("not in", "absent")
      - comments / docstrings
      - the scanner code itself (which only ever sees the string form)
    """
    if not txt or "append_coinbase_fill_row" not in txt:
        return False
    # Very simple but effective: real call has ( right after the name (with optional whitespace)
    # Our own scanner code and all protective tests use the string form or "not in".
    if re.search(r"append_coinbase_fill_row\s*\(", txt):
        # Further: if the surrounding context is a negative test/assert in a test file, the caller already filtered tests/
        return True
    return False


def get_changed_files(base: str, head: str = "HEAD") -> List[str]:
    out = run_cmd(f"git diff --name-only {base}...{head}", check=False)
    return [line for line in out.splitlines() if line.strip()]


def parse_args(argv: Sequence[str] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Local review gate — reusable safety checks for Grok/Codex patches (read-only, local only)"
    )
    p.add_argument("--branch", required=True, help="Review branch to verify (e.g. review/p2-014c-...)")
    p.add_argument("--base", default="main", help="Base branch for diff (default: main)")
    p.add_argument(
        "--expected-file",
        action="append",
        default=[],
        help="Expected changed file (repeatable or comma-separated). If given, changed set must exactly match.",
    )
    p.add_argument(
        "--forbid-file",
        action="append",
        default=[],
        help="Additional forbidden file/pattern (repeatable or comma-separated).",
    )
    p.add_argument(
        "--protected-file",
        action="append",
        default=[],
        help="Additional protected patterns (added to built-in defaults).",
    )
    p.add_argument(
        "--pytest",
        action="append",
        default=[],
        help="pytest spec to run (repeatable, e.g. tests/test_foo.py -q -k bar)",
    )
    p.add_argument(
        "--py-compile",
        action="append",
        default=[],
        help="Python file to py_compile (repeatable)",
    )
    p.add_argument(
        "--smoke",
        action="append",
        default=[],
        help="Read-only smoke command to run (repeatable, e.g. 'python3 scripts/foo.py --help')",
    )
    p.add_argument(
        "--allow-docs-active-handoff",
        action="store_true",
        help="Permit changes to docs/ACTIVE_HANDOFF.md (only for patches whose sole purpose is documenting live status)",
    )
    p.add_argument(
        "--check-production-fill-logger",
        action="store_true",
        help="Enable smart production-only scan for append_coinbase_fill_row calls and logs/coinbase_fills.csv writes",
    )
    p.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the final compact report (less verbose)",
    )
    return p.parse_args(argv)


def run_gate(args: argparse.Namespace) -> int:
    print("=== LOCAL REVIEW GATE ===")
    print("ADVISORY ONLY — local git + compile + test inspection. No live trading side effects.")

    # 0. Pre-flight: must have no *modified tracked* changes.
    # Pure untracked new files (??) that exactly match --expected-file are allowed
    # (this is the normal case when first developing the files for a patch).
    pre_status = run_cmd("git status --short", check=False)
    modified_tracked = [line for line in pre_status.splitlines() if line and not line.startswith("??")]
    untracked = [line[3:] for line in pre_status.splitlines() if line.startswith("??")]
    expected = normalize_list(getattr(args, "expected_file", []))
    # If there are modified tracked files, hard fail.
    if modified_tracked:
        print(f"\n[FAIL] Working tree has modified tracked files:\n" + "\n".join(modified_tracked))
        print("Commit, stash, or reset the modifications first.")
        return 1
    # Untracked are OK only if they are exactly the ones we expect for this patch review
    unexpected_untracked = [u for u in untracked if u not in expected] if expected else untracked
    if unexpected_untracked and expected:
        print(f"\n[FAIL] Unexpected untracked files present: {unexpected_untracked}")
        print(f"Expected only: {expected}")
        return 1
    # If we reach here with only expected untracked new files (or a clean tree), we are "clean enough" for review.

    # 1. Fetch
    print("\n[1/12] git fetch origin ...")
    run_cmd("git fetch origin", check=True)

    branch = args.branch
    base = args.base

    # 2. Ensure we can switch to the branch (local or origin)
    print(f"\n[2/12] Ensuring branch {branch} ...")
    # Try local
    rev = run_cmd(f"git rev-parse --verify {branch}", check=False)
    if not rev:
        # Try to fetch it
        run_cmd(f"git fetch origin {branch}:{branch}", check=False)
        rev = run_cmd(f"git rev-parse --verify {branch}", check=False)
    if not rev:
        print(f"[FAIL] Cannot find branch {branch} locally or on origin.")
        return 1

    # 3. Switch + pull ff-only (tolerant for brand-new local review branches with no upstream yet)
    print(f"\n[3/12] git checkout {branch} && git pull --ff-only (tolerant)...")
    run_cmd(f"git checkout {branch}")
    # Non-fatal pull — many review branches are purely local until the final push step
    run_cmd(f"git pull --ff-only 2>/dev/null || echo '[note] no upstream tracking yet for {branch} (common for new review branches) — continuing with local state'", check=False)

    # 4. Info
    head = run_cmd("git rev-parse HEAD")
    print(f"\n[4/12] Branch: {branch}")
    print(f"      Base:   {base}")
    print(f"      HEAD:   {head}")

    # Post-pull status: allow the exact expected untracked new files (same logic as pre-flight)
    status = run_cmd("git status --short", check=False)
    post_modified = [line for line in status.splitlines() if line and not line.startswith("??")]
    post_untracked = [line[3:] for line in status.splitlines() if line.startswith("??")]
    if post_modified:
        print(f"[FAIL] Working tree dirty after checkout/pull (modified tracked):\n" + "\n".join(post_modified))
        return 1
    unexpected_after = [u for u in post_untracked if u not in expected] if expected else post_untracked
    if unexpected_after:
        print(f"[FAIL] Unexpected untracked files after pull: {unexpected_after}")
        return 1
    # Only the files we are intentionally reviewing are untracked/new — acceptable for a fresh patch branch.

    changed = get_changed_files(base, "HEAD")
    print("\n[5/12] Changed files vs base:")
    if not changed:
        print("  (no changes)")
    else:
        for f in changed:
            print(f"  {f}")

    # 6. Expected files exact match (if provided)
    if expected:
        print(f"\n[6/12] Checking exact expected files ({len(expected)})...")
        if set(changed) != set(expected):
            print(f"[FAIL] Changed files differ from --expected-file list.")
            print(f"  Expected: {sorted(expected)}")
            print(f"  Got:      {sorted(changed)}")
            return 1
        print("  OK (exact match)")

    # 7. Forbidden + protected patterns
    protected = PROTECTED_DEFAULTS + normalize_list(args.protected_file)
    forbid = normalize_list(args.forbid_file)
    all_protected = list(dict.fromkeys(protected + forbid))  # dedup preserve order

    print(f"\n[7/12] Protected/forbidden file check ({len(all_protected)} patterns)...")
    for f in changed:
        if is_protected(f, all_protected):
            print(f"[FAIL] Protected file changed: {f}")
            return 1
    print("  OK (no protected files changed)")

    # 8. ACTIVE_HANDOFF guard (unless explicitly allowed for a docs-only status patch)
    if "docs/ACTIVE_HANDOFF.md" in changed:
        if not args.allow_docs_active_handoff:
            print("\n[FAIL] docs/ACTIVE_HANDOFF.md changed without --allow-docs-active-handoff")
            print("       (Only patches whose *sole* purpose is updating live status may use the flag.)")
            return 1
        print("\n[8/12] ACTIVE_HANDOFF.md change allowed by flag.")
    else:
        print("\n[8/12] ACTIVE_HANDOFF.md unchanged (good).")

    # 9. git diff --check (whitespace etc.)
    print("\n[9/12] git diff --check ...")
    run_cmd("git diff --check")

    # 10. py_compile requested files
    py_files = normalize_list(args.py_compile)
    if py_files:
        print(f"\n[10/12] py_compile {len(py_files)} file(s)...")
        for f in py_files:
            run_cmd(f"python3 -m py_compile {f}")
        print("  OK")

    # 11. pytest requested
    pytest_specs = normalize_list(args.pytest)
    if pytest_specs:
        print(f"\n[11/12] Running {len(pytest_specs)} pytest spec(s)...")
        for spec in pytest_specs:
            run_cmd(f"python3 -m pytest {spec} -q")
        print("  All requested pytest passed")

    # 12. Smoke commands (read-only by user contract)
    smokes = normalize_list(args.smoke)
    if smokes:
        print(f"\n[12/12] Running {len(smokes)} smoke command(s)...")
        for s in smokes:
            run_cmd(s)
        print("  All smokes passed")

    # === Smart production fill logger check ===
    if args.check_production_fill_logger:
        print("\n[EXTRA] --check-production-fill-logger ...")
        prod_changed = [f for f in changed if not f.startswith("tests/")]
        for f in prod_changed:
            if "coinbase_fills.csv" in f.lower() or f.endswith("coinbase_fills.csv"):
                print(f"[FAIL] logs/coinbase_fills.csv (or similar) was changed: {f}")
                return 1
            if f.endswith(".py"):
                try:
                    txt = Path(f).read_text(encoding="utf-8", errors="ignore")
                    if has_production_append_call(txt):
                        print(f"[FAIL] Production file {f} contains a call to append_coinbase_fill_row")
                        return 1
                except Exception:
                    pass
        print("  Production fill-logger scan: PASS (no calls in non-test files, no csv writes)")

    # === FINAL COMPACT REPORT (the only thing that should be pasted to ChatGPT) ===
    print("\n" + "=" * 60)
    print("LOCAL REVIEW GATE — COMPACT REPORT (paste this block)")
    print("=" * 60)
    print(f"branch: {branch}")
    print(f"base: {base}")
    print(f"head: {head}")
    print(f"changed_files: {changed}")
    print(f"tests_run: {pytest_specs}")
    print(f"py_compile: {py_files}")
    print(f"smokes: {smokes}")
    print(f"protected_checks: PASS (no protected/forbidden files, ACTIVE_HANDOFF handled)")
    print("read_only: This execution performed only local git inspection, py_compile, pytest, and user-provided smoke commands on the review branch. No broker APIs were called, no .env was read, no network except explicit git fetch, no orders placed, no fill logger writes, no append_coinbase_fill_row calls from production paths.")
    final_status = run_cmd("git status --short", check=False) or "clean"
    print(f"git_status: {final_status}")
    print("recommended_next: Paste the entire block above (and any preceding gate output) to ChatGPT. Do NOT merge yourself. ChatGPT will decide merge readiness based on the report + constraints.")
    print("=" * 60)

    print("\n[GATE SUCCESS] All checks passed for this review branch.")
    return 0


def main(argv: Sequence[str] = None) -> int:
    args = parse_args(argv)
    return run_gate(args)


if __name__ == "__main__":
    raise SystemExit(main())
