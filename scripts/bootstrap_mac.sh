#!/usr/bin/env bash
# bootstrap_mac.sh — One-time setup for the trading bot on macOS.
# Run once after cloning or when setting up a new machine.
# Creates the venv, installs all dependencies, and sets secure permissions.
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BOT_DIR"

echo "=== Trading Bot Bootstrap ==="
echo "Directory: $BOT_DIR"
echo ""

# Create required directories
mkdir -p logs journal runtime state/alpaca state/coinbase scripts launchd

# Create venv if it doesn't exist
if [[ ! -d ".venv" ]]; then
    echo "Creating Python venv..."
    python3 -m venv .venv
    echo "Venv created."
else
    echo "Venv already exists — skipping creation."
fi

# Activate and install dependencies
source .venv/bin/activate
echo "Installing dependencies..."
python -m pip install --upgrade pip setuptools wheel --quiet
pip install -r requirements.txt --quiet
pip freeze > requirements.lock.txt
echo "Dependencies installed. requirements.lock.txt updated."

# Secure .env files
for env_file in .env .env.alpaca .env.coinbase .env.alerts; do
    if [[ -f "$env_file" ]]; then
        chmod 600 "$env_file"
        echo "Secured: $env_file (chmod 600)"
    fi
done

echo ""
echo "=== Bootstrap complete ==="
echo ""
echo "Next steps:"
echo "  1. Verify API keys in .env (or .env.alpaca / .env.coinbase)"
echo "  2. Install launchd agents (run scripts/install_launchd.sh)"
echo "  3. Check status: scripts/status.sh"
