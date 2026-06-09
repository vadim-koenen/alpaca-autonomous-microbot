#!/usr/bin/env bash
# handoff_status_sync.sh — Mac-native, ZERO-AI status sync for GPT/Claude shared context.
# Replaces the Claude scheduled tasks (coinbase-bot-spot-check, bot-handoff-sync) — no credits.
#
# What it does (read-only w.r.t. broker/orders/.env):
#   1. Runs scripts/audit_snapshot.sh (live economics digest).
#   2. Snapshots both heartbeats + journal state.
#   3. Writes docs/STATUS_AUTO.md (overwrite) + appends docs/STATUS_AUTO_LOG.md (history).
#   4. Commits + pushes them to the ops/status branch via an ISOLATED git worktree,
#      so your working branch and the running bot are never touched.
#
# GPT reads shared context from:  branch ops/status -> docs/STATUS_AUTO.md
# Schedule via launchd: see docs/AUTOMATION_SETUP.md.

set -uo pipefail
REPO="/Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot"
WT="$HOME/.investing_status_worktree"     # OUTSIDE the repo — never pollutes your tree
BRANCH="ops/status"
cd "$REPO" || exit 1
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

hb() { python3 -c "import json;print(json.load(open('$1')).get('$2',''))" 2>/dev/null; }
CB=runtime/coinbase_heartbeat.json
AL=runtime/alpaca_heartbeat.json

AUDIT="$(bash scripts/audit_snapshot.sh 2>/dev/null)"
VERDICT="$(printf '%s\n' "$AUDIT" | grep '^AUDIT_VERDICT=' | tail -1)"
DIGEST="$(printf '%s\n' "$AUDIT" | grep -E 'cycles=' | tail -1)"
HEAD="$(git log --oneline -1 2>/dev/null)"
ERR="$(tail -200 logs/coinbase.launchd.out.log 2>/dev/null | grep -cE 'ERROR|CRITICAL')"

CB_STATUS=$(hb $CB status); CB_EQ=$(hb $CB equity); CB_POS=$(hb $CB open_positions)
CB_PNL=$(hb $CB daily_pnl); CB_TRADE=$(hb $CB last_trade_at); CB_LOOP=$(hb $CB last_loop_time); CB_HALT=$(hb $CB halt_reason)
AL_STATUS=$(hb $AL status); AL_EQ=$(hb $AL equity); AL_POS=$(hb $AL open_positions); AL_LOOP=$(hb $AL last_loop_time)

# isolated worktree on ops/status (created once; never touches your checked-out branch)
if [ ! -e "$WT/.git" ]; then
  git fetch origin "$BRANCH" >/dev/null 2>&1
  git worktree add -B "$BRANCH" "$WT" "origin/$BRANCH" >/dev/null 2>&1 \
    || git worktree add -B "$BRANCH" "$WT" >/dev/null 2>&1
fi
mkdir -p "$WT/docs"

cat > "$WT/docs/STATUS_AUTO.md" <<EOF
# Auto Status (machine-generated — do not hand-edit)

Generated: $(ts)
Main-tree HEAD: $HEAD
Audit verdict: $VERDICT

## Coinbase (live)
status=$CB_STATUS  equity=$CB_EQ  open_positions=$CB_POS  daily_pnl=$CB_PNL
last_trade_at=$CB_TRADE  last_loop_time=$CB_LOOP  halt_reason=$CB_HALT

## Alpaca
status=$AL_STATUS  equity=$AL_EQ  open_positions=$AL_POS  last_loop_time=$AL_LOOP

## Economics digest
$DIGEST
recent_log_errors(last200 lines)=$ERR

## Full audit snapshot
\`\`\`
$AUDIT
\`\`\`
EOF

echo "- $(ts) | cb_eq=$CB_EQ pos=$CB_POS pnl=$CB_PNL | $VERDICT | $DIGEST | head=${HEAD%% *}" >> "$WT/docs/STATUS_AUTO_LOG.md"

git -C "$WT" add docs/STATUS_AUTO.md docs/STATUS_AUTO_LOG.md >/dev/null 2>&1
if git -C "$WT" commit -m "auto: status sync $(ts)" >/dev/null 2>&1; then
  git -C "$WT" push -u origin "$BRANCH" >/dev/null 2>&1 && echo "synced+pushed $(ts) $VERDICT" || echo "committed (push failed) $(ts)"
else
  echo "no change $(ts)"
fi
