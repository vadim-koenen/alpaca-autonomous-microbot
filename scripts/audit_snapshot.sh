#!/usr/bin/env bash
# audit_snapshot.sh — broker/runtime/trading-read-only spot-check of live economics.
# Data-first: reads the journal, config, and git. No broker calls, no .env, no orders.
# Not filesystem-read-only: writes reports/spot_checks/last_net.txt when executed.
# Emits a human digest to stdout and a machine verdict line: AUDIT_VERDICT=OK|WARN|CRITICAL
#
# Usage: bash scripts/audit_snapshot.sh
# Exit code: 0=OK, 1=WARN, 2=CRITICAL

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

JOURNAL="journal_coinbase_crypto.csv"
CONFIG="config_coinbase_crypto.yaml"
STATE_DIR="reports/spot_checks"
LAST_NET_FILE="$STATE_DIR/last_net.txt"
mkdir -p "$STATE_DIR"

# Baseline: live EXIT cycles BEFORE this date are historical (pre-turnaround).
# New live exits from paused strategies AFTER this date are a regression.
BASELINE_DATE="2026-06-02"
PAUSED_STRATS="recovered mean_reversion coinbase_probe"

flags=()   # collected WARN/CRITICAL reasons

echo "=== AUDIT SNAPSHOT $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "=== GIT HEAD ==="
git --no-pager log --oneline -6 2>/dev/null || echo "(git unavailable)"

# ---- column indices by header name (robust to schema drift) ----
hdr=$(head -1 "$JOURNAL")
col() { echo "$hdr" | tr ',' '\n' | grep -n "^$1$" | head -1 | cut -d: -f1; }
C_MODE=$(col mode); C_ACT=$(col action); C_STRAT=$(col strategy)
C_SYM=$(col symbol); C_REASON=$(col reason); C_PNL=$(col pnl_usd); C_TS=$(col timestamp)

echo "=== LIVE P/L TRUTH (mode=live, action=EXIT) ==="
read -r CYC WINS NET <<<"$(awk -F, -v m=$C_MODE -v a=$C_ACT -v p=$C_PNL \
  '$m=="live"&&$a=="EXIT"{c++; n+=$p; if($p>0)w++} END{printf "%d %d %.4f",c,w,n}' "$JOURNAL")"
WR=$(awk -v w=$WINS -v c=$CYC 'BEGIN{printf "%.1f", (c>0?100*w/c:0)}')
echo "cycles=$CYC wins=$WINS win_rate=${WR}% cumulative_net_usd=$NET"

echo "=== EXIT REASONS (live) ==="
awk -F, -v m=$C_MODE -v a=$C_ACT -v r=$C_REASON '$m=="live"&&$a=="EXIT"{print $r}' "$JOURNAL" \
  | sed 's/[0-9.]*min.*/min (timeout)/' | sort | uniq -c | sort -rn | head
TIMEOUT=$(awk -F, -v m=$C_MODE -v a=$C_ACT -v r=$C_REASON '$m=="live"&&$a=="EXIT"&&$r ~ /max hold/{t++} END{print t+0}' "$JOURNAL")

echo "=== NET BY STRATEGY (live EXIT) ==="
awk -F, -v m=$C_MODE -v a=$C_ACT -v s=$C_STRAT -v p=$C_PNL \
  '$m=="live"&&$a=="EXIT"{n[$s]+=$p;c[$s]++} END{for(x in n)printf "%-22s c=%d net=%.4f\n",x,c[x],n[x]}' "$JOURNAL"

echo "=== ACTIVITY (last 3 live-EXIT days) ==="
awk -F, -v m=$C_MODE -v a=$C_ACT -v t=$C_TS '$m=="live"&&$a=="EXIT"{print substr($t,1,10)}' "$JOURNAL" \
  | sort | uniq -c | tail -3

echo "=== RISK CONFIG ==="
grep -iE 'probe_enabled|_notional_usd|max_open_positions|max_trade_notional|take_profit_pct|stop_loss_pct' "$CONFIG" 2>/dev/null

# ================= TRIPWIRES =================
# CRITICAL: $0.50 probe (or any probe) re-enabled
if grep -qiE '^[[:space:]]*coinbase_probe_enabled:[[:space:]]*true' "$CONFIG" 2>/dev/null; then
  flags+=("CRITICAL: coinbase_probe_enabled=true (structurally fee-negative path re-enabled)")
fi
# CRITICAL: caps raised beyond approved limits
MAXNOT=$(grep -iE '^[[:space:]]*max_trade_notional_usd:' "$CONFIG" | head -1 | grep -oE '[0-9.]+')
[ -n "${MAXNOT:-}" ] && awk -v v="$MAXNOT" 'BEGIN{exit !(v>10.0001)}' && flags+=("CRITICAL: max_trade_notional_usd=$MAXNOT > 10 (cap raised)")
MAXOPEN=$(grep -iE '^[[:space:]]*max_open_positions:' "$CONFIG" | head -1 | grep -oE '[0-9]+')
[ -n "${MAXOPEN:-}" ] && [ "$MAXOPEN" -gt 1 ] 2>/dev/null && flags+=("CRITICAL: max_open_positions=$MAXOPEN > 1")
# CRITICAL: a paused strategy produced NEW live exits after baseline
for s in $PAUSED_STRATS; do
  newc=$(awk -F, -v m=$C_MODE -v a=$C_ACT -v st=$C_STRAT -v t=$C_TS -v s="$s" -v b="$BASELINE_DATE" \
    '$m=="live"&&$a=="EXIT"&&$st==s&&substr($t,1,10)>b{c++} END{print c+0}' "$JOURNAL")
  [ "${newc:-0}" -gt 0 ] && flags+=("CRITICAL: paused strategy '$s' produced $newc new live exit(s) after $BASELINE_DATE")
done
# CRITICAL: cumulative net dropped > $1.00 since last snapshot (active bleeding)
if [ -f "$LAST_NET_FILE" ]; then
  PREV=$(cat "$LAST_NET_FILE")
  DROP=$(awk -v a="$PREV" -v b="$NET" 'BEGIN{printf "%.4f", a-b}')
  awk -v d="$DROP" 'BEGIN{exit !(d>1.0)}' && flags+=("CRITICAL: cumulative net fell by \$$DROP since last check (was $PREV, now $NET)")
fi
echo "$NET" > "$LAST_NET_FILE"
# WARN: exits still dominated by timeouts
[ "$CYC" -gt 0 ] && awk -v t="$TIMEOUT" -v c="$CYC" 'BEGIN{exit !(t*1.0/c>0.5)}' && flags+=("WARN: ${TIMEOUT}/${CYC} live exits are time-based (exit logic not fixed)")
# WARN: win rate below 45% with enough sample
[ "$CYC" -ge 20 ] && awk -v w="$WR" 'BEGIN{exit !(w<45)}' && flags+=("WARN: win_rate ${WR}% < 45% over $CYC cycles")

# ================= VERDICT =================
echo "=== FINDINGS ==="
verdict="OK"; rc=0
if [ ${#flags[@]} -eq 0 ]; then
  echo "(none) — within expected bounds"
else
  for f in "${flags[@]}"; do echo "- $f"; case "$f" in CRITICAL*) verdict="CRITICAL";; WARN*) [ "$verdict" = OK ] && verdict="WARN";; esac; done
fi
[ "$verdict" = "WARN" ] && rc=1
[ "$verdict" = "CRITICAL" ] && rc=2
echo "AUDIT_VERDICT=$verdict"
exit $rc
