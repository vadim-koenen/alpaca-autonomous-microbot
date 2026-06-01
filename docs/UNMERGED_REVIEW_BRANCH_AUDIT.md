# UNMERGED REVIEW BRANCH AUDIT

**Purpose**: This document tracks YELLOW review branches that must not be merged without explicit ChatGPT review. It exists to prevent accidental self-merges of work that carries reconciliation, broker truth, or risk implications.

**Current main HEAD**: e48f0b7 (after P2-018F second overnight run)

**Date of this audit**: Second overnight autonomy run

---

## Unmerged Branches

### 1. review/p2-017d-coinbase-full-fill-payload-capture
- **Commit on branch**: f8dc271
- **Risk classification**: YELLOW
- **Why unmerged**:
  - The branch contains the first controlled live read-only capture for the matched SOL trade_id (1f10a7cb-3fe5-4cbb-b990-f74c39529fc9).
  - The original transcript summarized the live result instead of printing the exact required live JSON key fields as specified in the P2-017D task.
  - This work directly touches deeper broker payload reconciliation for the still-open SOL position.
- **What must be verified before merge**:
  - Exact live JSON output from the capture command (with all required fields: verdict, profit_readout, source_mode, live_read_only, broker_calls_made, broker_read_successful, direct_fee_available, direct_filled_value_available, candidate paths, sanitized keys, etc.).
  - Confirmation that output was properly sanitized (no secrets, no raw account IDs).
  - Confirmation that no state, logs, or config were mutated during the capture.
  - Confirmation that the capture did not place/cancel/close any orders.
- **Explicit rule**: Do not merge overnight. Requires full ChatGPT review with the actual live JSON before any merge decision.
- **Profit readout status**: Remains unsafe_to_aggregate.
- **Risk increase**: Not approved.
- **Next ChatGPT review questions**:
  - Does the live output provide direct non-null fee and filled_value for the entry leg?
  - Is the output fully sanitized?
  - Does this change the evidence level for the open SOL lot?
  - Should any part of the capture logic be hardened or made safer before landing on main?

### 2. review/p2-018e-local-review-gate-reconciliation-safety
- **Commit on branch**: e53b426
- **Risk classification**: YELLOW
- **Why unmerged**:
  - The patch attempts to expand the local review gate with additional reconciliation safety checks.
  - The static pattern scanning produced noisy/false-positive results on legitimate protective code and existing scripts that reference .env or config for valid reasons.
  - Expanding gate logic carries risk of accidentally blocking safe future work or missing real violations.
- **What must be verified before merge**:
  - A clean, low-noise implementation that only flags actual dangerous production patterns (writing to logs/coinbase_fills.csv, calling append_coinbase_fill_row outside tests, modifying config_coinbase_crypto.yaml, modifying LaunchAgents, running live mode by default in offline scripts, etc.).
  - The checks must not create false positives on existing safe code (broker_coinbase.py, utilities, review gate itself).
  - Tests must be reliable and not brittle.
- **Explicit rule**: Do not merge overnight. Requires careful ChatGPT review of the actual diff and test behavior.
- **Profit readout status**: Remains unsafe_to_aggregate.
- **Risk increase**: Not approved.
- **Next ChatGPT review questions**:
  - Is the pattern matching precise enough?
  - Does it correctly protect the reconciliation invariants without over-blocking?
  - Should the checks be limited to specific directories (e.g., scripts/ excluding known safe files)?

---

## General Rules for These Branches

- No live broker calls are permitted in any verification or testing of these branches without explicit new approval.
- No orders, cancels, closes, or modifications of any kind.
- No changes to config_coinbase_crypto.yaml or risk/sizing parameters.
- No modifications to LaunchAgents, launchd, or background runtime.
- No state file mutations.
- No writing to logs/coinbase_fills.csv or calling append_coinbase_fill_row in production paths.
- Profit readout remains unsafe_to_aggregate while the open SOL position and incomplete direct fee/filled_value evidence persist.
- Risk increase is not approved.

These branches exist to protect the long-running reconciliation and broker-truth work. They must be treated with the same caution as any change that could affect P/L truth or risk gates.

**End of audit document.** Update this file whenever new unmerged review branches are created that carry reconciliation or risk implications.