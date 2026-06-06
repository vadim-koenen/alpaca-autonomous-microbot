#!/usr/bin/env bash
# Activate STOP_TRADING and verify Coinbase/Alpaca live processes actually exit.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash scripts/stop_all_verified.sh [--wait-seconds N] [--poll-seconds N]
       [--term-after N] [--kill-after N]

The default sends no signals. --term-after and --kill-after are explicit
operator escalation choices. STOP_TRADING is created and never removed.
USAGE
}

WAIT_SECONDS=90
POLL_SECONDS=2
TERM_AFTER=""
KILL_AFTER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wait-seconds) WAIT_SECONDS="${2:-}"; shift 2 ;;
    --poll-seconds) POLL_SECONDS="${2:-}"; shift 2 ;;
    --term-after) TERM_AFTER="${2:-}"; shift 2 ;;
    --kill-after) KILL_AFTER="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
done

for value in "$WAIT_SECONDS" "$POLL_SECONDS" ${TERM_AFTER:+"$TERM_AFTER"} ${KILL_AFTER:+"$KILL_AFTER"}; do
  [[ "$value" =~ ^[0-9]+$ ]] || { echo "ERROR: timing values must be nonnegative integers" >&2; exit 64; }
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="${BOT_DIR_OVERRIDE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PGREP_BIN="${PGREP_BIN:-pgrep}"
KILL_BIN="${KILL_BIN:-kill}"
STOP_FILE="$BOT_DIR/runtime/STOP_TRADING"
LOCK_FILES=("$BOT_DIR/runtime/coinbase.lock" "$BOT_DIR/runtime/alpaca.lock")

mkdir -p "$BOT_DIR/runtime"
touch "$STOP_FILE"
echo "STOP_TRADING active: $STOP_FILE"

live_process_pids() {
  "$PGREP_BIN" -f "main.py --mode live" 2>/dev/null || true
}

lock_pids() {
  local lock raw pid
  for lock in "${LOCK_FILES[@]}"; do
    [[ -f "$lock" ]] || continue
    raw="$(<"$lock")"
    pid="${raw//[^0-9]/}"
    [[ -n "$pid" ]] || continue
    if "$KILL_BIN" -0 "$pid" 2>/dev/null; then
      printf '%s\n' "$pid"
    fi
  done
}

all_pids() {
  { live_process_pids; lock_pids; } | awk 'NF && !seen[$0]++'
}

start_seconds=$SECONDS
term_sent=false
kill_sent=false

while true; do
  pids=()
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && pids+=("$pid")
  done < <(all_pids)
  elapsed=$((SECONDS - start_seconds))
  if [[ ${#pids[@]} -eq 0 ]]; then
    echo "VERIFIED_STOPPED elapsed_seconds=$elapsed"
    exit 0
  fi

  echo "STILL_RUNNING elapsed_seconds=$elapsed pids=${pids[*]}"

  if [[ -n "$TERM_AFTER" && "$term_sent" == false && $elapsed -ge $TERM_AFTER ]]; then
    echo "Explicit --term-after reached; sending SIGTERM to: ${pids[*]}"
    "$KILL_BIN" -TERM "${pids[@]}"
    term_sent=true
  fi
  if [[ -n "$KILL_AFTER" && "$kill_sent" == false && $elapsed -ge $KILL_AFTER ]]; then
    echo "Explicit --kill-after reached; sending SIGKILL to: ${pids[*]}"
    "$KILL_BIN" -KILL "${pids[@]}"
    kill_sent=true
  fi

  if [[ $elapsed -ge $WAIT_SECONDS ]]; then
    echo "ERROR: live processes remain after ${WAIT_SECONDS}s: ${pids[*]}" >&2
    exit 2
  fi
  sleep "$POLL_SECONDS"
done
