#!/usr/bin/env bash
# run_alpaca_stocks.sh — Launch the Alpaca stocks-only bot.
#
# Crypto is DISABLED. Equities (SPY, QQQ, AAPL, MSFT, NVDA) are live-enabled.
# Uses Alpaca API keys from .env (ALPACA_API_KEY / ALPACA_SECRET_KEY).
#
# Usage:
#   ./run_alpaca_stocks.sh          → paper mode
#   ./run_alpaca_stocks.sh paper    → paper mode
#   ./run_alpaca_stocks.sh live     → live mode (requires LIVE_TRADING=true in .env)
#   ./run_alpaca_stocks.sh diagnose → indicator snapshot, no orders

MODE="${1:-paper}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BROKER=alpaca CONFIG_FILE=config_alpaca_stocks.yaml \
    bash "$SCRIPT_DIR/run.sh" "$MODE"
