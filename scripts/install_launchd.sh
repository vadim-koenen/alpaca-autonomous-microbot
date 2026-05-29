#!/usr/bin/env bash
# install_launchd.sh — Install both bot launchd agents.
# After running this, both bots start automatically at login and
# restart after crashes. No terminal window needed.
#
# To uninstall: scripts/uninstall_launchd.sh
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS" "$BOT_DIR/logs"

ALPACA_PLIST="$BOT_DIR/launchd/com.vadim.alpaca-bot.plist"
COINBASE_PLIST="$BOT_DIR/launchd/com.vadim.coinbase-crypto-bot.plist"

echo "=== Installing launchd agents ==="

# Unload first if already loaded (prevents duplicate load errors)
launchctl unload "$LAUNCH_AGENTS/com.vadim.alpaca-bot.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_AGENTS/com.vadim.coinbase-crypto-bot.plist" 2>/dev/null || true

# Copy plists to LaunchAgents
cp "$ALPACA_PLIST" "$LAUNCH_AGENTS/"
cp "$COINBASE_PLIST" "$LAUNCH_AGENTS/"
echo "Plists copied to $LAUNCH_AGENTS"

# Load agents
launchctl load "$LAUNCH_AGENTS/com.vadim.alpaca-bot.plist"
launchctl load "$LAUNCH_AGENTS/com.vadim.coinbase-crypto-bot.plist"

echo ""
echo "=== Agents installed and loaded ==="
echo ""
echo "Check status:    scripts/status.sh"
echo "Watch logs:      scripts/tail_logs.sh"
echo "Stop all bots:   scripts/stop_all.sh"
echo ""
echo "Bots will auto-start at login and restart after crashes."
echo "They will NOT restart if stopped cleanly (kill switch or Ctrl+C)."
