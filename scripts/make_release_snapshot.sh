#!/usr/bin/env bash
# make_release_snapshot.sh — create a local code/docs snapshot without secrets.
#
# This script does not deploy, restart, or place broker actions.

set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$BOT_DIR/VERSION"
VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
OUT_DIR="$BOT_DIR/releases"
BASE="alpaca_microbot_${VERSION}_${STAMP}"
ARCHIVE="$OUT_DIR/${BASE}.tar.gz"
MANIFEST="$OUT_DIR/${BASE}.manifest.json"

mkdir -p "$OUT_DIR"

git_hash="unavailable"
if command -v git >/dev/null 2>&1 && git -C "$BOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git_hash="$(git -C "$BOT_DIR" rev-parse HEAD)"
fi

test_count="unknown"
if [[ -d "$BOT_DIR/tests" ]]; then
    test_count="$(find "$BOT_DIR/tests" -maxdepth 1 -type f -name 'test_*.py' | wc -l | tr -d ' ') files"
fi

tar \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='logs' \
    --exclude='releases' \
    --exclude='memory/bot_memory.sqlite3' \
    --exclude='secrets' \
    -czf "$ARCHIVE" \
    -C "$BOT_DIR" \
    .

python3 - "$MANIFEST" "$VERSION" "$STAMP" "$git_hash" "$test_count" "$ARCHIVE" <<'PY'
import json
import sys
from pathlib import Path

manifest, version, stamp, git_hash, test_count, archive = sys.argv[1:]
payload = {
    "version": version,
    "created_at_utc": stamp,
    "git_hash": git_hash,
    "test_count": test_count,
    "archive": str(Path(archive)),
    "excluded": [
        ".env",
        ".env.*",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "*.pyc",
        "logs",
        "releases",
        "memory/bot_memory.sqlite3",
        "secrets",
    ],
    "deploys": False,
    "restarts_bots": False,
}
Path(manifest).write_text(json.dumps(payload, indent=2, sort_keys=True))
PY

echo "Release snapshot written:"
echo "  $ARCHIVE"
echo "  $MANIFEST"
