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
