#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT="${APP_SHELL_PORT:-8080}"
URL="http://localhost:${PORT}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="reports/app_shell"
LOG_FILE="${LOG_DIR}/app_shell_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

echo "=== Investing Bot App Shell Launcher ==="
echo "repo_root=$REPO_ROOT"
echo "url=$URL"
echo "log_file=$LOG_FILE"

if lsof -iTCP:"$PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  echo "status=already_running"
  open "$URL"
  exit 0
fi

echo "status=starting"
nohup env PYTHONPATH=".:scripts" python3 scripts/run_app_shell.py > "$LOG_FILE" 2>&1 &
APP_PID="$!"

sleep 2

if lsof -iTCP:"$PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  echo "status=started"
  echo "pid=$APP_PID"
  open "$URL"
  exit 0
fi

echo "status=failed_to_start"
echo "pid=$APP_PID"
echo "log_file=$LOG_FILE"
tail -80 "$LOG_FILE" 2>/dev/null || true
exit 1
