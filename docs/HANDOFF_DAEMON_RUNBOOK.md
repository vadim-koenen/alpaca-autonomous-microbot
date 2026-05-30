# ADVISORY ONLY — tooling automation only, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

# Handoff Automation Daemon Runbook — P2-001I

## Purpose
The Handoff Automation Daemon is a polling service that automates the update of `docs/ACTIVE_HANDOFF.md` after a functional patch has been committed. It acts as a bridge between the developer (or AI) and the `complete_patch.py` script, allowing updates to be triggered asynchronously via a JSON marker file.

## How It Works
1. **Marker Detection**: The daemon polls for `docs/PENDING_PATCH_COMPLETION.json`.
2. **Validation**: It parses the JSON, verifies all required fields are present, and checks that the `patch_commit` exists in the local git history.
3. **Safety Check**: It verifies that no tracked files are dirty (except for the handoff itself and the marker).
4. **Execution**: It invokes `scripts/complete_patch.py` with `--commit --push --verify-raw`.
5. **Archiving**: Upon success, it moves the marker to `docs/completed_patch_requests/` with a timestamp.

## How to Trigger
To trigger an update, create `docs/PENDING_PATCH_COMPLETION.json` with the following structure:

```json
{
  "patch": "P2-001I",
  "title": "Handoff automation daemon",
  "patch_commit": "<your_commit_hash>",
  "summary": "Adds polling daemon to automate ACTIVE_HANDOFF updates",
  "next": "P2-002 — Prediction features review",
  "created_at": "2026-05-30T10:00:00Z",
  "created_by": "gemini"
}
```

## How to Install (Manual step, requires Vadim approval)
```bash
# 1. Copy the plist to LaunchAgents
cp launchd/com.vadim.handoff-daemon.plist ~/Library/LaunchAgents/

# 2. Load the daemon
launchctl load ~/Library/LaunchAgents/com.vadim.handoff-daemon.plist
```

## How to Check Status
```bash
launchctl list | grep handoff-daemon
```

## How to Watch Logs
```bash
# Main activity log
tail -f logs/handoff_daemon.log

# Stdout/Stderr from launchd
tail -f logs/handoff_daemon.out.log
tail -f logs/handoff_daemon.err.log
```

## How to Manually Trigger
If you don't want to wait for the 5-minute interval:
```bash
python3 scripts/handoff_daemon.py --once
```

## Failure Modes
- **Invalid JSON/Missing Fields**: The error is logged to `logs/handoff_daemon.log`, and the marker file is preserved.
- **Commit Not Found**: The daemon will exit with an error and leave the marker.
- **Dirty Git State**: If other files are modified, the daemon will refuse to run to avoid accidental commits.
- **Network Errors**: If `push` fails, the error is logged and the marker is preserved.

## What the Daemon May NOT Do
- **NEVER** run `git add .` or `git commit -a`.
- **NEVER** touch any files in `broker/`, `order_manager.py`, `risk_manager.py`, or `main.py`.
- **NEVER** restart any trading bots.
- **NEVER** modify `.env` or read secrets.
- **NEVER** modify any files outside of `docs/` and `logs/handoff_daemon.log`.
