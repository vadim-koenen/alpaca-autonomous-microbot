#!/usr/bin/env bash
# start_all.sh — Remove kill switch and restart both bots via launchd.
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SWITCH="$BOT_DIR/runtime/STOP_TRADING"

if [[ -f "$SWITCH" ]]; then
    rm "$SWITCH"
    echo "Kill switch removed."
fi

launchctl start com.vadim.alpaca-bot 2>/dev/null && echo "Alpaca bot started." || echo "Alpaca bot not loaded in launchd — run scripts/install_launchd.sh first."
launchctl start com.vadim.coinbase-crypto-bot 2>/dev/null && echo "Coinbase bot started." || echo "Coinbase bot not loaded in launchd — run scripts/install_launchd.sh first."

echo ""
echo "Check status: scripts/status.sh"
