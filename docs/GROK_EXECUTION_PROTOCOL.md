# GROK EXECUTION PROTOCOL

This document defines the standard, repeatable workflow for Grok (the coding execution layer) when working on the Investing Bot project.

## Core Principles

- **Safety first**: Never increase trading aggressiveness, risk, sizing, or autonomy without explicit ChatGPT approval.
- **Git hygiene**: Always work on review branches. Never push directly to main.
- **Verification discipline**: Every change must be accompanied by tests, safety checks, and a clean verification transcript.
- **Minimal scope**: Commit and push only the files that are part of the approved task.
- **No unapproved live actions**: Do not place, cancel, close, or modify orders unless the task explicitly authorizes it and safety review has occurred.

## Standard Workflow (Grok)

1. **Start from main**
   - `git fetch origin`
   - `git switch main`
   - `git pull --ff-only origin main`

2. **Create or reuse a review branch**
   - Use the naming convention: `review/<task-id>-<short-description>`
   - Example: `review/p2-015c-live-probe-reliability-and-schema`

3. **Implement the approved changes**
   - Make only the minimal changes required by the task.
   - Update tests for any code changes.
   - Update documentation where relevant (without touching ACTIVE_HANDOFF.md unless explicitly approved in the task).

4. **Run full verification**
   - `python3 -m py_compile <changed scripts>`
   - Relevant pytest suites
   - `git --no-pager diff --check`
   - Default text and JSON smoke tests (where applicable)
   - Production safety check (the AST-based forbidden calls/mutations check)
   - Confirm no `.replace()` in production scripts if the safety gate is active for the task

5. **Commit only intended files**
   - Use the exact commit message provided in the task (if any).
   - Never include unintended files.

6. **Push the review branch only**
   - `git push origin <branch-name>`
   - Do **not** merge to main unless ChatGPT has explicitly approved the merge in a prior message for this specific branch.

7. **If ChatGPT approves merge**
   - Return to main
   - Fast-forward only: `git merge --ff-only <branch>`
   - Push main
   - Update ACTIVE_HANDOFF.md (only after successful fast-forward merge)
   - Commit and push the handoff update
   - Run post-merge verification

8. **Produce final verification transcript**
   - Use the exact format requested in the task.

## Required Transcript Fields (when requested)

- branch
- commit hash
- changed files
- exact tests run + results
- safety check result (PRODUCTION_SAFETY_CHECK: PASS/FAIL)
- text smoke output
- JSON smoke output (parsed key fields)
- git diff --check result
- git status --short
- git log --oneline (last N commits)
- merged / NOT MERGED
- profit/momentum readout status
- next recommended action

## Hard Safety Constraints (never bypass)

- No unapproved live strategy, risk, sizing, or cap changes.
- No unverified merge to main.
- No risk/cap/sizing/aggressiveness increase without explicit ChatGPT approval.
- No strategy self-modification based on short-term performance.
- No leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG.
- No order placement, cancel, close, or modify unless the specific task authorizes it and safety review has passed.
- No writes to journal, state, runtime, or log files except for explicitly approved documentation or test fixtures on the review branch.
- No `append_coinbase_fill_row` production calls.
- No exposure or printing of secrets/API keys (only boolean or redacted status is allowed).

## When to Stop

If any verification step fails (tests, safety check, diff --check, JSON schema, etc.), stop immediately, summarize the failure, and do not proceed to merge or further changes without new instructions.

This protocol exists to keep the project safe, auditable, and aligned with long-term goals of durable, reconciled, low-risk autonomy.

---
*Last updated as part of P2-016A planning docs.*