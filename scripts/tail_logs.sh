#!/usr/bin/env bash
# tail_logs.sh — Watch live logs from both bots simultaneously.
# Press Ctrl+C to stop watching (does not stop the bots).

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

ALPACA_LOG="$BOT_DIR/logs/alpaca.launchd.out.log"
COINBASE_LOG="$BOT_DIR/logs/coinbase.launchd.out.log"

# Fall back to session logs if launchd logs don't exist yet
if [[ ! -f "$ALPACA_LOG" ]]; then
    ALPACA_LOG=$(ls -t "$BOT_DIR/logs/session_alpaca_"*.log 2>/dev/null | head -1 || echo "")
fi
if [[ ! -f "$COINBASE_LOG" ]]; then
    COINBASE_LOG=$(ls -t "$BOT_DIR/logs/session_coinbase_"*.log 2>/dev/null | head -1 || echo "")
fi

echo "Watching logs. Ctrl+C to stop (bots keep running)."
echo ""

# Use multitail if available, otherwise fall back to tail -f with prefixes
if command -v multitail &>/dev/null; then
    multitail -l "tail -f $ALPACA_LOG" -l "tail -f $COINBASE_LOG"
else
    FILES=()
    [[ -n "$ALPACA_LOG" && -f "$ALPACA_LOG" ]] && FILES+=("$ALPACA_LOG")
    [[ -n "$COINBASE_LOG" && -f "$COINBASE_LOG" ]] && FILES+=("$COINBASE_LOG")

    if [[ ${#FILES[@]} -eq 0 ]]; then
        echo "No log files found yet. Start the bots first."
        exit 1
    fi

    tail -f "${FILES[@]}"
fi
