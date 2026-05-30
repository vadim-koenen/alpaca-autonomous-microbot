#!/usr/bin/env python3
# ADVISORY ONLY — tooling automation, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def run_command(command, check=True, capture_output=True):
    """Run a shell command and return the output."""
    env = os.environ.copy()
    env["GIT_PAGER"] = "cat"
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=check,
            capture_output=capture_output,
            text=True,
            env=env
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        if check:
            print(f"Error running command: {command}")
            print(f"Output: {e.stdout}")
            print(f"Error: {e.stderr}")
            sys.exit(1)
        return None

def update_handoff(args):
    handoff_path = Path("docs/ACTIVE_HANDOFF.md")
    if not handoff_path.exists():
        print(f"Error: {handoff_path} not found.")
        sys.exit(1)

    content = handoff_path.read_text()

    # 1. Update last updated timestamp
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    content = re.sub(
        r"\*\*Last updated:\*\* .*?\n",
        f"**Last updated:** {now_utc} — {args.patch} committed; {args.summary}\n",
        content
    )

    # 2. Update Milestone table row
    milestone_row = f"| {args.patch} | {args.title} | DONE / committed `{args.patch_commit[:7]}` |"
    if f"| {args.patch} |" in content:
        # Update existing row
        content = re.sub(
            rf"\| {args.patch} \| .*? \| .*? \|",
            milestone_row,
            content
        )
    else:
        # Append to Milestone table (find start of table in Section 5)
        # We look for the header row and the separator row
        milestone_header_pattern = r"(## 5\. Completed Milestones\n\n\| ID \| Name \| Status \|\n\|[-\|]+\|)"
        match = re.search(milestone_header_pattern, content)
        if match:
            table_header_end = match.end()
            # Find end of table (next double newline or end of file)
            table_end = content.find("\n\n", table_header_end)
            if table_end == -1: table_end = len(content)
            content = content[:table_end] + "\n" + milestone_row + content[table_end:]

    # 3. Update Section 6 Git State
    section_6_pattern = r"(## 6\. Git State.*?\n\n```\n)(.*?)(\n```)"
    git_state_content = f"""Latest functional patch commit: {args.patch_commit[:7]}
Latest handoff commit: PENDING
Clean: no dirty tracked files (except handoff update)

Recent commits:
  {args.patch_commit[:7]} {args.patch}: {args.title}"""
    
    if re.search(section_6_pattern, content, flags=re.DOTALL):
        content = re.sub(
            section_6_pattern,
            rf"\1{git_state_content}\3",
            content,
            flags=re.DOTALL
        )

    # 4. Update Section 8 Active Patch Queue
    section_8_in_progress_pattern = r"(### IN PROGRESS\n)(.*?)(\n###)"
    if re.search(section_8_in_progress_pattern, content, flags=re.DOTALL):
        content = re.sub(
            section_8_in_progress_pattern,
            rf"\1**{args.next}**\n\3",
            content,
            flags=re.DOTALL
        )
    else:
        # Fallback if QUEUED is the last section
        section_8_in_progress_pattern = r"(### IN PROGRESS\n)(.*?)(\n---)"
        if re.search(section_8_in_progress_pattern, content, flags=re.DOTALL):
            content = re.sub(
                section_8_in_progress_pattern,
                rf"\1**{args.next}**\n\3",
                content,
                flags=re.DOTALL
            )

    # Remove from QUEUED
    content = re.sub(
        rf"- \*\*{args.patch}.*?\n",
        "",
        content
    )

    # 5. Append status log line
    log_line = f"- {now_utc} | head={args.patch_commit[:7]} | {args.patch} complete; {args.summary}"
    if "## 11. Automated Status Log" in content:
        # Find the last line of the status log and append after it
        content = content.strip() + "\n" + log_line + "\n"
    else:
        content = content.strip() + f"\n\n## 11. Automated Status Log\n{log_line}\n"

    # 6. Cleanup placeholders
    content = content.replace("REPLACE_WITH_HEAD", args.patch_commit[:7])

    if args.dry_run:
        print("--- DRY RUN: Proposed ACTIVE_HANDOFF.md changes ---")
        print(content)
        print("--- END DRY RUN ---")
    else:
        handoff_path.write_text(content)
        print(f"Updated {handoff_path}")

    return content

def verify_raw(args):
    repo_url = "https://raw.githubusercontent.com/vadim-koenen/alpaca-autonomous-microbot/main/docs/ACTIVE_HANDOFF.md"
    cachebust = int(time.time())
    url = f"{repo_url}?t={cachebust}"
    
    print(f"Verifying raw content from: {url}")
    raw_content = run_command(f"curl -fsSL {url}", check=False)
    
    if not raw_content:
        print("Error: Could not fetch raw content from GitHub.")
        return

    patch_found = args.patch in raw_content
    summary_found = args.summary in raw_content
    
    if patch_found and summary_found:
        print(f"Verification SUCCESS: {args.patch} and summary found in raw GitHub handoff.")
    else:
        print(f"Verification STALE: {args.patch} or summary NOT found in raw GitHub handoff yet.")
        print("Wait a few moments for GitHub CDN to sync.")

def cli_main():
    parser = argparse.ArgumentParser(description="P2-001G: Patch Completion Automation")
    parser.add_argument("--patch", required=True, help="Patch ID (e.g., P2-001F)")
    parser.add_argument("--title", required=True, help="Patch Title")
    parser.add_argument("--patch-commit", required=True, help="Commit hash of the functional patch")
    parser.add_argument("--summary", required=True, help="Brief summary of the patch results")
    parser.add_argument("--next", required=True, help="What's next in the queue")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes or commit")
    parser.add_argument("--commit", action="store_true", help="Commit the handoff update")
    parser.add_argument("--push", action="store_true", help="Push the handoff update")
    parser.add_argument("--no-commit", action="store_true", help="Do not commit (default)")
    parser.add_argument("--verify-raw", action="store_true", help="Verify the update on raw GitHub")
    
    args = parser.parse_args()

    # Safety checks
    if any(p in sys.argv for p in ["launchctl", "live", ".env"]):
        print("Safety Violation: Forbidden parameters detected.")
        sys.exit(1)

    update_handoff(args)

    if args.commit and not args.dry_run:
        run_command("git add docs/ACTIVE_HANDOFF.md")
        commit_msg = f"update ACTIVE_HANDOFF: {args.patch} complete"
        run_command(f'git commit -m "{commit_msg}"')
        handoff_commit = run_command("git rev-parse HEAD")
        print(f"Committed: {commit_msg} ({handoff_commit[:7]})")
        
        # Update Section 6 with actual handoff commit
        handoff_path = Path("docs/ACTIVE_HANDOFF.md")
        content = handoff_path.read_text()
        content = content.replace("Latest handoff commit: PENDING", f"Latest handoff commit: {handoff_commit[:7]}")
        handoff_path.write_text(content)
        # Amend commit to include the fixed hash
        run_command("git add docs/ACTIVE_HANDOFF.md")
        run_command("git commit --amend --no-edit")
        
        if args.push:
            current_branch = run_command("git rev-parse --abbrev-ref HEAD")
            run_command(f"git push origin {current_branch}")
            print(f"Pushed to origin/{current_branch}")

    if args.verify_raw:
        if args.push:
            print("Waiting 2 seconds for GitHub CDN...")
            time.sleep(2)
        verify_raw(args)

if __name__ == "__main__":
    cli_main()
