#!/usr/bin/env bash
# stop_all.sh — Gracefully stop both bots via the global kill switch.
# The bots detect the file on their next cycle and shut down cleanly.
# Positions are NOT automatically closed — the position monitor continues
# managing existing stops/TPs until the process exits.
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SWITCH="$BOT_DIR/runtime/STOP_TRADING"

mkdir -p "$BOT_DIR/runtime"
touch "$SWITCH"
echo "Kill switch activated: $SWITCH"
echo ""
echo "Both bots will halt on their next cycle (within ~60 seconds)."
echo "To resume trading, remove the kill switch and restart:"
echo "  rm $SWITCH"
echo "  scripts/start_all.sh   (or launchctl start com.vadim.alpaca-bot etc.)"
