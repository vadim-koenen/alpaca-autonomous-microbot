#!/usr/bin/env bash
# sync_handoff.sh — Auto-commit and push ACTIVE_HANDOFF.md to GitHub.
# Runs on a schedule via launchd. No manual intervention needed.
# Only commits if the file has actually changed — idempotent.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
HANDOFF="$REPO/docs/ACTIVE_HANDOFF.md"
LOG="$REPO/logs/handoff_sync.log"

mkdir -p "$REPO/logs"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

# Only proceed if the handoff file exists
if [[ ! -f "$HANDOFF" ]]; then
    echo "$(timestamp) | SKIP: ACTIVE_HANDOFF.md not found" >> "$LOG"
    exit 0
fi

cd "$REPO"

# Stage the handoff file
git add "$HANDOFF"

# Only commit if there's actually a change
if git diff --cached --quiet; then
    echo "$(timestamp) | OK: no changes to push" >> "$LOG"
    exit 0
fi

# Commit and push
git commit -m "auto-sync handoff $(date '+%Y-%m-%dT%H:%M')" >> "$LOG" 2>&1
git push origin main >> "$LOG" 2>&1

echo "$(timestamp) | PUSHED: ACTIVE_HANDOFF.md synced to GitHub" >> "$LOG"
