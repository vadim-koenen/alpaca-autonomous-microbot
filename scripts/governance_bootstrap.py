#!/usr/bin/env python3
"""
Governance Bootstrap / Dependency-Aware Patch Starter.
"""
import argparse
import subprocess
import sys
from pathlib import Path

def run_cmd(cmd, shell=False, check=True, capture=True, dry_run=False, action_desc=""):
    if dry_run:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        print(f"[DRY-RUN] {action_desc}: {cmd_str}")
        return ""
        
    res = subprocess.run(cmd, shell=shell, text=True, capture_output=capture)
    if check and res.returncode != 0:
        print(f"Command failed: {cmd}\n{res.stderr}")
        sys.exit(res.returncode)
    return res.stdout.strip() if capture else res.returncode

def file_exists_on_ref(ref, filepath, dry_run=False):
    if dry_run:
        # In dry run, we actually need to evaluate this to branch properly, so we don't dry-run this check
        res = subprocess.run(["git", "cat-file", "-e", f"{ref}:{filepath}"], capture_output=True)
        return res.returncode == 0
    res = subprocess.run(["git", "cat-file", "-e", f"{ref}:{filepath}"], capture_output=True)
    return res.returncode == 0

def remote_branch_exists(branch):
    res = subprocess.run(["git", "ls-remote", "--heads", "origin", branch], capture_output=True, text=True)
    return bool(res.stdout.strip())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start"])
    parser.add_argument("--patch", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--requires-file", required=True)
    parser.add_argument("--dependency-branch", required=True)
    parser.add_argument("--dependency-commit", required=True)
    parser.add_argument("--base", default="main")
    parser.add_argument("--transcript")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    transcript = []
    def record(msg):
        print(msg)
        transcript.append(msg)
        
    record(f"=== GOVERNANCE BOOTSTRAP: {args.patch} ===")
    
    def run_logic():
        # We always run fetch to get truth, even in dry run
        record("Fetching origin...")
        subprocess.run(["git", "fetch", "origin", "--prune"], capture_output=True)
        
        base_has_file = file_exists_on_ref(args.base, args.requires_file, args.dry_run)
        
        if base_has_file:
            record(f"{args.requires_file} exists on {args.base}.")
            if args.base == "main":
                # check up to date with origin/main
                local_main = subprocess.run(["git", "rev-parse", "main"], capture_output=True, text=True).stdout.strip()
                remote_main = subprocess.run(["git", "rev-parse", "origin/main"], capture_output=True, text=True).stdout.strip()
                if local_main != remote_main:
                    record("WARNING: local main differs from origin/main. Consider pulling.")
            
            run_cmd(["git", "checkout", "-b", args.branch, args.base], dry_run=args.dry_run, action_desc="Create branch from base")
            record("NEXT_ACTION=created_from_base")
            
        else:
            record(f"{args.requires_file} does NOT exist on {args.base}.")
            record(f"Checking dependency branch {args.dependency_branch}...")
            
            dep_exists = remote_branch_exists(args.dependency_branch)
            if not dep_exists:
                record(f"ABORT: required file missing from base, and dependency branch {args.dependency_branch} not found on origin.")
                sys.exit(1)
                
            remote_dep_head = subprocess.run(["git", "ls-remote", "origin", args.dependency_branch], capture_output=True, text=True).stdout.split()[0]
            if remote_dep_head != args.dependency_commit:
                record(f"ABORT: remote dependency branch HEAD ({remote_dep_head}) does not match expected commit ({args.dependency_commit}).")
                sys.exit(1)
                
            dep_has_file = file_exists_on_ref(f"origin/{args.dependency_branch}", args.requires_file, args.dry_run)
            if not dep_has_file:
                record(f"ABORT: required file missing from base and dependency branch. Run/merge dependency first.")
                sys.exit(1)
                
            record(f"{args.requires_file} exists on origin/{args.dependency_branch}.")
            run_cmd(["git", "checkout", "-b", args.branch, f"origin/{args.dependency_branch}"], dry_run=args.dry_run, action_desc="Create branch from dependency")
            record("NEXT_ACTION=created_from_dependency_branch")
            record("MERGE ORDER REQUIRED: merge dependency branch first, then rebase/merge this child branch after dependency lands.")
            
    try:
        run_logic()
    finally:
        if args.transcript:
            transcript_text = "\n".join(transcript)
            try:
                Path(args.transcript).write_text(transcript_text, encoding="utf-8")
                record(f"Transcript written to {args.transcript}")
            except Exception as e:
                print(f"Warning: Failed to write transcript to {args.transcript}: {e}")
                
        # pbcopy
        try:
            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            process.communicate("\n".join(transcript))
        except Exception:
            pass

if __name__ == "__main__":
    main()
