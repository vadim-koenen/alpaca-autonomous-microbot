#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/clear_recovered_position.sh --broker coinbase|alpaca --key <position_key> --reason <text>

Safely moves one recovered position from state/<broker>/open_positions.json to
state/<broker>/closed_positions.json. The selected bot must be stopped first.
USAGE
}

BROKER=""
POSITION_KEY=""
CLEAR_REASON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --broker)
      BROKER="${2:-}"
      shift 2
      ;;
    --key)
      POSITION_KEY="${2:-}"
      shift 2
      ;;
    --reason)
      CLEAR_REASON="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done

if [[ "$BROKER" != "coinbase" && "$BROKER" != "alpaca" ]]; then
  echo "ERROR: --broker must be coinbase or alpaca" >&2
  usage >&2
  exit 64
fi

if [[ -z "$POSITION_KEY" ]]; then
  echo "ERROR: --key is required" >&2
  usage >&2
  exit 64
fi

if [[ -z "$CLEAR_REASON" ]]; then
  echo "ERROR: --reason is required" >&2
  usage >&2
  exit 64
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="${BOT_DIR_OVERRIDE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
STATE_DIR="$BOT_DIR/state/$BROKER"
OPEN_FILE="$STATE_DIR/open_positions.json"
CLOSED_FILE="$STATE_DIR/closed_positions.json"
LOCK_FILE="$BOT_DIR/runtime/$BROKER.lock"
HEARTBEAT_FILE="$BOT_DIR/runtime/${BROKER}_heartbeat.json"

python3 - "$BROKER" "$LOCK_FILE" "$HEARTBEAT_FILE" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

broker, lock_path, heartbeat_path = sys.argv[1:4]


def pid_is_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_int(path):
    try:
        raw = open(path, encoding="utf-8").read().strip()
    except FileNotFoundError:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    return int(digits) if digits else None


lock_pid = read_int(lock_path)
if lock_pid and pid_is_alive(lock_pid):
    print(
        f"ERROR: {broker} bot appears to be running "
        f"(runtime lock pid {lock_pid}). Stop it before modifying state.",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    with open(heartbeat_path, encoding="utf-8") as handle:
        heartbeat = json.load(handle)
except FileNotFoundError:
    heartbeat = {}
except json.JSONDecodeError:
    heartbeat = {}

heartbeat_pid = heartbeat.get("pid")
if isinstance(heartbeat_pid, int) and heartbeat_pid > 0 and pid_is_alive(heartbeat_pid):
    print(
        f"ERROR: {broker} bot appears to be running "
        f"(heartbeat pid {heartbeat_pid}). Stop it before modifying state.",
        file=sys.stderr,
    )
    sys.exit(2)

last_loop = heartbeat.get("last_loop_time")
if heartbeat.get("status") == "running" and isinstance(last_loop, str):
    try:
        parsed = datetime.fromisoformat(last_loop.replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    except ValueError:
        age_seconds = None
    if age_seconds is not None and age_seconds < 120:
        print(
            f"ERROR: {broker} heartbeat is still fresh ({age_seconds:.0f}s old). "
            "Wait for the bot to stop before modifying state.",
            file=sys.stderr,
        )
        sys.exit(2)
PY

python3 - "$BROKER" "$POSITION_KEY" "$CLEAR_REASON" "$OPEN_FILE" "$CLOSED_FILE" <<'PY'
import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

broker, position_key, clear_reason, open_path, closed_path = sys.argv[1:6]


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return copy.deepcopy(default)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def atomic_write(path, payload):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


open_state = load_json(open_path, {"state_namespace": broker, "positions": {}})
positions = open_state.get("positions")
if not isinstance(positions, dict):
    print(f"ERROR: {open_path} does not contain a positions object", file=sys.stderr)
    sys.exit(1)

if position_key not in positions:
    print(f"ERROR: position key not found in open positions: {position_key}", file=sys.stderr)
    sys.exit(3)

removed = positions.pop(position_key)
if not isinstance(removed, dict):
    removed = {"value": removed}

now = datetime.now(timezone.utc).isoformat()
closed_state = load_json(
    closed_path,
    {
        "description": "Archive of positions removed from open state after manual operator review.",
        "state_namespace": broker,
        "positions": {},
    },
)
closed_positions = closed_state.setdefault("positions", {})
if not isinstance(closed_positions, dict):
    print(f"ERROR: {closed_path} does not contain a positions object", file=sys.stderr)
    sys.exit(1)

archive_entry = copy.deepcopy(removed)
archive_entry.update(
    {
        "position_key": position_key,
        "status": "manually_cleared",
        "cleared_at": now,
        "cleared_reason": clear_reason,
        "cleared_by_script": True,
    }
)

stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z").replace(".", "_")
base_archive_key = f"{position_key}_manual_clear_{stamp}"
archive_key = base_archive_key
suffix = 2
while archive_key in closed_positions:
    archive_key = f"{base_archive_key}_{suffix}"
    suffix += 1

closed_positions[archive_key] = archive_entry
open_state["state_namespace"] = broker
open_state["saved_at"] = now
closed_state["state_namespace"] = broker
closed_state["saved_at"] = now

atomic_write(closed_path, closed_state)
atomic_write(open_path, open_state)

remaining = len(positions)
print(f"Cleared recovered position: broker={broker} key={position_key}")
print(f"Archived as: {archive_key}")
print(f"Open positions remaining: {remaining}")
print("Reason recorded in closed_positions.json.")
print("No broker orders were placed, canceled, or modified.")
print("Restart remains manual; review status/reconcile output before restarting.")
PY
