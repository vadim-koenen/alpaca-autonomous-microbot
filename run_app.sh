#!/usr/bin/env bash
# Launch the Accumulator desktop app from the repo, using the repo's .venv if present.
#   ./run_app.sh            # opens the app window
#   ./run_app.sh --cli      # headless: print status + this week's plan
#   ./run_app.sh --cli --approve   # simulate-approve one period (local state only)
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python3 ]; then
  PY=.venv/bin/python3
else
  PY=python3
fi

# Ensure the GUI dep is present (no-op if already installed).
if ! "$PY" -c "import webview" 2>/dev/null; then
  echo "[run_app] installing pywebview into the venv…"
  "$PY" -m pip install --quiet pywebview || {
    echo "[run_app] pip install failed; for the window you need pywebview. Try: $PY -m pip install pywebview"; }
fi

exec "$PY" app_main.py "$@"
