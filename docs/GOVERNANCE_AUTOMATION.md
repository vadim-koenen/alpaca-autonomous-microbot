# Governance Automation

## Purpose
The purpose of `scripts/governance_gate.py` is to reduce manual verification overhead for code patches by providing a repeatable local command for validating branch integrity, testing, and patch safety. It helps ensure that code being pushed up for review complies with strict rules surrounding live trading systems.

## Usage
The primary command to verify a review branch is:
```bash
python3 scripts/governance_gate.py verify-review \
    --branch <branch_name> \
    --base <base_branch> \
    --smoke "<smoke_command>" \
    --transcript <path/to/transcript.txt>
```

**Example:**
```bash
python3 scripts/governance_gate.py verify-review \
--branch review/p2-035a-operational-net-alerts \
--base origin/main \
--smoke "ENABLE_MACOS_ALERTS=0 python3 scripts/p2_035a_operational_net_smoke.py" \
--transcript /tmp/p2_035a_governance_verify.txt
```

## Dependency-aware bootstrap
If a required governance tool is present on a dependency branch but not yet merged to `main`, starting new work can lead to missing-file aborts. `scripts/governance_bootstrap.py` safely navigates this by creating your new patch branch either from `main` (if the tool is there) or from the dependency branch itself.

**Example for P2-035J:**
```bash
python3 scripts/governance_bootstrap.py start \
--patch P2-035J \
--branch review/p2-035j-governance-approval-workflow \
--requires-file scripts/governance_gate.py \
--dependency-branch review/p2-035a-operational-net-alerts \
--dependency-commit b853050fe384720ddb024720d40c0cd18156b9e5 \
--base main \
--transcript /tmp/p2_035j_bootstrap.txt
```

*Merge order remains dependency first. This reduces dead-ends and manual setup, but does not remove merge/restart approvals.*

## What Still Requires Human Approval
This script assists in local verification before pushing to origin, but it **does not replace human review**.
The following actions always require explicit human approval and are not fully automated:
- Merging to `main`.
- Restarting the live bot.
- Updating broker API keys or permissions.
- Changing trading logic, sizes, caps, symbols, or exits.
- Touching the `STOP_TRADING` or `launchctl` mechanisms.

## Approvals and Sandboxing
- The governance script is read-only (except for compiling files and running tests). It does not automatically merge. Merges must be done locally by an authorized user using an exact approval phrase (e.g. `MERGE_APPROVED for <branch> at <hash>`).
- Live bot runs are isolated; this script does not execute broker calls unless explicitly passed in a smoke test that has bypass permissions. 
- You may encounter sandbox isolation blocking network calls (like `git push`) when running this from an automated assistant context. This is expected. Just manually execute the push command yourself.
