#!/usr/bin/env bash
# run.sh — Unified launcher for the autonomous micro-bot.
#
# Usage:
#   ./run.sh                  → paper mode, default config (config.yaml)
#   ./run.sh paper            → paper mode
#   ./run.sh live             → LIVE mode (requires LIVE_TRADING=true in .env)
#   ./run.sh dry_run          → dry_run mode (no orders, no API state)
#   ./run.sh diagnose         → one-shot indicator snapshot, exits immediately
#
# Broker / config override (env vars):
#   BROKER=alpaca  CONFIG_FILE=config_alpaca_stocks.yaml   ./run.sh paper
#   BROKER=coinbase CONFIG_FILE=config_coinbase_crypto.yaml ./run.sh dry_run
#
# Or use the convenience wrappers:
#   ./run_alpaca_stocks.sh [mode]
#   ./run_coinbase_crypto.sh [mode]
#
# Kill switch (graceful shutdown without Ctrl+C):
#   mkdir -p runtime && touch runtime/STOP_TRADING
# Remove the file to allow restart:
#   rm runtime/STOP_TRADING
#
# Logs: logs/session_<mode>_<timestamp>.log — also echoed to terminal
# Ctrl+C once → graceful shutdown | Ctrl+C twice → force quit

set -euo pipefail

MODE="${1:-paper}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Resolve broker and config from env (defaults if not set)
BROKER="${BROKER:-alpaca}"
CONFIG_FILE="${CONFIG_FILE:-config.yaml}"

# Activate virtual environment if present
VENV="$SCRIPT_DIR/.venv"
if [[ -d "$VENV" ]]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
fi

# Warn loudly if going live
if [[ "$MODE" == "live" ]]; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║   ⚠  LIVE TRADING MODE — REAL MONEY AT RISK  ⚠          ║"
    echo "║   Max trade: \$2  |  Max exposure: \$4  |  Loss limit: \$2  ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
    echo "  broker=$BROKER  config=$CONFIG_FILE"
    echo ""
    echo "  Starting in 5 seconds. Ctrl+C NOW to abort."
    echo ""
    sleep 5
fi

# Handle diagnose mode separately (no log file needed)
if [[ "$MODE" == "diagnose" ]]; then
    echo "Running one-shot diagnose — no orders will be placed."
    BROKER="$BROKER" CONFIG_FILE="$CONFIG_FILE" python3 "$SCRIPT_DIR/main.py" --mode paper --diagnose
    exit 0
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/session_${BROKER}_${MODE}_${TIMESTAMP}.log"

echo ""
echo "Starting bot | broker=$BROKER | config=$CONFIG_FILE | mode=$MODE"
echo "Log: $LOG_FILE"
echo "Kill switch: mkdir -p runtime && touch runtime/STOP_TRADING"
echo "Press Ctrl+C once to shut down gracefully."
echo ""

BROKER="$BROKER" CONFIG_FILE="$CONFIG_FILE" python3 "$SCRIPT_DIR/main.py" --mode "$MODE" 2>&1 | tee "$LOG_FILE"
