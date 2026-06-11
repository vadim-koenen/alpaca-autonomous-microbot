#!/usr/bin/env bash
# ADVISORY ONLY — read-only repo state snapshot for pasting into chat agents
# (chat-GPT/Grok) that lack direct GitHub access. Never prints secrets,
# .env contents, or generated reports/.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== AGENT SYNC BUNDLE — $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo
echo "--- remotes (sanitized) ---"
git remote -v | sed 's#https://[^@]*@#https://#'
echo
echo "--- main ---"
git fetch origin --quiet || echo "(fetch failed — offline? showing cached state)"
git log -3 --format='%h %s (%cd)' --date=short origin/main
echo
echo "--- review/* branches (remote) ---"
for b in $(git branch -r --format='%(refname:short)' | grep '^origin/review/' ); do
  echo "$b -> $(git log -1 --format='%h %s (%cd)' --date=short "$b")"
done
echo
echo "--- local vs origin/main ---"
git status --short --branch | head -5
echo
echo "--- latest ACTIVE_HANDOFF entry ---"
awk '/^## /{c++} c==2{exit} c>=1' docs/ACTIVE_HANDOFF.md | head -40
echo
echo "=== END BUNDLE ==="
