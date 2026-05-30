# ADVISORY ONLY — tooling automation, no live trading calls.

# Patch Completion Automation Runbook — P2-001G

## Overview

The Patch Completion Automation tool (`scripts/complete_patch.py`) is a Class 1 advisory script designed to automate the error-prone task of updating `docs/ACTIVE_HANDOFF.md` after a functional patch has been committed.

It ensures that:
1. The **Last updated** timestamp is current.
2. The **Completed Milestones** table includes the new patch.
3. The **Git State** correctly reflects the latest patch commit and handoff commit.
4. The **Active Patch Queue** is cleaned up (moving the current patch to DONE and setting the next task).
5. The **Automated Status Log** is appended.

---

## Quick Start

```bash
# 1. Run with dry-run to verify proposed changes
python3 scripts/complete_patch.py \
  --patch P2-001F \
  --title "Coinbase maker order audit" \
  --patch-commit f835e74 \
  --summary "6/6 entries likely passive-priced; actual maker/taker fee-side unproven" \
  --next "None — awaiting review" \
  --dry-run

# 2. Execute and commit locally
python3 scripts/complete_patch.py \
  --patch P2-001F \
  --title "Coinbase maker order audit" \
  --patch-commit f835e74 \
  --summary "6/6 entries likely passive-priced" \
  --next "None — awaiting review" \
  --commit

# 3. Execute, commit, and push with verification
python3 scripts/complete_patch.py \
  --patch P2-001F \
  --title "Coinbase maker order audit" \
  --patch-commit f835e74 \
  --summary "6/6 entries likely passive-priced" \
  --next "None — awaiting review" \
  --commit \
  --push \
  --verify-raw
```

---

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--patch` | Yes | Patch ID (e.g., `P2-001F`). |
| `--title` | Yes | Brief title of the patch. |
| `--patch-commit` | Yes | The 7-char or full commit hash of the functional change. |
| `--summary` | Yes | A concise (1-sentence) summary of the results. |
| `--next` | Yes | Description of what's next in the queue (or `None`). |
| `--dry-run` | No | Print changes to stdout without writing to disk. |
| `--commit` | No | Stage and commit `docs/ACTIVE_HANDOFF.md`. |
| `--push` | No | Push the current branch after committing. |
| `--verify-raw` | No | Fetch raw GitHub URL to verify CDN sync. |

---

## Safety Mandates

1. **Advisory Only**: This script only modifies documentation. It never touches trading logic.
2. **Restricted Scope**: By default, it only modifies `docs/ACTIVE_HANDOFF.md`.
3. **No Global Add**: Uses `git add docs/ACTIVE_HANDOFF.md` specifically; never `git add .`.
4. **Forbidden Parameters**: Will abort if `live`, `launchctl`, or `.env` are passed as arguments.

---

## Verification

The `--verify-raw` flag performs an automated check:
1. It waits 2 seconds (if pushed) for CDN propagation.
2. It fetches the raw `ACTIVE_HANDOFF.md` from GitHub with a cache-busting timestamp.
3. It confirms that the Patch ID and Summary are present in the remote file.

---

## Troubleshooting

### "Error: docs/ACTIVE_HANDOFF.md not found"
Ensure you are running the script from the project root.

### "Verification STALE"
GitHub's CDN can take up to 60 seconds to refresh. If the script reports STALE, wait a minute and check manually.

### "Regex match failed"
If the structure of `ACTIVE_HANDOFF.md` changes significantly, the regex patterns in `scripts/complete_patch.py` may need adjustment.

---

**Last Updated:** 2026-05-30
**Status:** ACTIVE — Tooling automation.
