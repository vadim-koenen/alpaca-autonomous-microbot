#!/usr/bin/env python3
# ADVISORY ONLY — tooling automation only, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).parent.parent
MARKER_FILE = REPO_ROOT / "docs" / "PENDING_PATCH_COMPLETION.json"
COMPLETED_DIR = REPO_ROOT / "docs" / "completed_patch_requests"
LOG_FILE = REPO_ROOT / "logs" / "handoff_daemon.log"
COMPLETE_PATCH_SCRIPT = REPO_ROOT / "scripts" / "complete_patch.py"

REQUIRED_FIELDS = ["patch", "title", "patch_commit", "summary", "next", "created_at", "created_by"]

def log_event(status, patch, message):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    log_line = f"{timestamp} | {status:6} | {patch:8} | {message}\n"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(log_line)
    print(log_line.strip())

def check_git_status():
    """Verify only allowed files are dirty."""
    result = subprocess.run(
        ["git", "status", "--short"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    if result.returncode != 0:
        return False, "Failed to run git status"

    allowed_dirty = {"docs/ACTIVE_HANDOFF.md", "docs/PENDING_PATCH_COMPLETION.json"}
    lines = result.stdout.strip().split("\n")
    for line in lines:
        if not line:
            continue
        # Status is usually XY path
        status = line[:2].strip()
        path = line[3:].strip()
        
        # We only care about tracked files that are dirty
        # Untracked files (??) are ignored for this check unless they interfere
        if "?" not in status and path not in allowed_dirty:
            return False, f"Unexpected dirty tracked file: {path}"
                
    return True, ""

def run_cycle(dry_run=False):
    # Step 1: Check for marker file
    if not MARKER_FILE.exists():
        return 0

    # Step 2: Parse JSON
    try:
        with open(MARKER_FILE, "r") as f:
            data = json.load(f)
    except Exception as e:
        log_event("ERROR", "UNKNOWN", f"Malformed JSON in marker: {str(e)}")
        return 1

    # Validate fields
    patch_id = data.get("patch", "UNKNOWN")
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        log_event("ERROR", patch_id, f"Missing required fields: {', '.join(missing)}")
        return 1

    # Step 3: Verify patch_commit exists
    patch_commit = data["patch_commit"]
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{patch_commit}^{{commit}}"],
        capture_output=True,
        cwd=REPO_ROOT
    )
    if result.returncode != 0:
        log_event("ERROR", patch_id, f"Commit {patch_commit} not found in git")
        return 1

    # Step 4: Check git status
    status_ok, status_msg = check_git_status()
    if not status_ok:
        log_event("ERROR", patch_id, status_msg)
        return 1

    if dry_run:
        log_event("DRYRUN", patch_id, "Validation passed. Would call complete_patch.py")
        return 0

    # Step 5: Call complete_patch.py
    cmd = [
        sys.executable,
        str(COMPLETE_PATCH_SCRIPT),
        "--patch", data["patch"],
        "--title", data["title"],
        "--patch-commit", data["patch_commit"],
        "--summary", data["summary"],
        "--next", data["next"],
        "--commit", "--push", "--verify-raw"
    ]
    
    log_event("START", patch_id, "Calling complete_patch.py")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    
    if result.returncode != 0:
        log_event("ERROR", patch_id, f"complete_patch.py failed. Output: {result.stdout} {result.stderr}")
        return 1

    # Step 6: Move marker to archive
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
    iso_ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
    archive_path = COMPLETED_DIR / f"{iso_ts}_{patch_id}.json"
    
    try:
        shutil.move(str(MARKER_FILE), str(archive_path))
    except Exception as e:
        log_event("ERROR", patch_id, f"Failed to archive marker: {str(e)}")
        return 1

    # Step 7: Final log
    log_event("SUCCESS", patch_id, f"Handoff updated and marker archived to {archive_path.name}")
    return 0

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Handoff Automation Daemon")
    parser.add_argument("--dry-run", action="store_true", help="Validate but do not modify anything")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    # The user instruction says it's called by launchd every 300s.
    # If not --once, we could loop, but the requirement implies launchd handles the interval.
    # "Called by launchd every 300 seconds." -> It should run once and exit.
    
    sys.exit(run_cycle(dry_run=args.dry_run))
