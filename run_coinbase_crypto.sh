#!/usr/bin/env bash
# run_coinbase_crypto.sh — Launch the Coinbase crypto-only bot.
#
# Equities, options, margin, and short selling are ALL disabled.
# No paper mode on Coinbase — use dry_run for safe simulation.
# Uses Coinbase API keys from .env (COINBASE_API_KEY / COINBASE_API_SECRET).
#
# Prerequisites:
#   1. Add your Coinbase Advanced Trade API keys to .env:
#        COINBASE_API_KEY=your_key_here
#        COINBASE_API_SECRET=your_secret_here
#   2. Create keys at: https://www.coinbase.com/settings/api
#      Key type: Advanced Trade | Permissions: View + Trade
#
# Usage:
#   ./run_coinbase_crypto.sh           → dry_run (no real orders — safe to test)
#   ./run_coinbase_crypto.sh dry_run   → same as above
#   ./run_coinbase_crypto.sh live      → real orders (requires LIVE_TRADING=true in .env)
#   ./run_coinbase_crypto.sh diagnose  → indicator snapshot, no orders

MODE="${1:-dry_run}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BROKER=coinbase CONFIG_FILE=config_coinbase_crypto.yaml \
    bash "$SCRIPT_DIR/run.sh" "$MODE"
