# Agent Sync Protocol — Claude / Codex / chat-GPT / Grok

Adopted 2026-06-10. Applies to every AI agent session touching this repo.

## The one rule

**An update does not exist until it is (a) pushed to GitHub and (b) reflected in `docs/ACTIVE_HANDOFF.md`.**

GitHub (`vadim-koenen/alpaca-autonomous-microbot`) is the only state all agents can reach. Local-only commits, chat messages, and unsaved analysis are invisible to other agents.

## Who can see what

| Agent | Repo visibility | Write path |
|---|---|---|
| Claude (Cowork) | Direct: local clone + push | Branches via local git |
| Codex | Direct: GitHub | Branches/merges via GitHub |
| chat-GPT (no connector) | **None** — only pasted text/uploads | None — outputs must be saved & committed by Vadim or another agent |
| Grok | Per GROK_EXECUTION_PROTOCOL | Per its gate docs |

If a chat-GPT session needs repo state, give it a **sync bundle** (below) or enable the ChatGPT GitHub connector.

## End-of-turn checklist (every agent, every session)

1. Commit work to a `review/*` branch (never directly to `main`; merges require Vadim's approval phrase).
2. Push the branch.
3. Add/refresh the topmost entry in `docs/ACTIVE_HANDOFF.md` (patch ID, branch, commit, status, next step) — directly or via `docs/PENDING_PATCH_COMPLETION.json` + handoff daemon.
4. If another agent must act next, state it explicitly in the handoff entry ("Next: Claude senior review of <branch> at <commit>").

## Sync bundle (for agents without repo access)

Run `scripts/agent_sync_bundle.sh` and paste its entire output into the chat session. It contains: current branch/commit for main and all `review/*` branches, the latest ACTIVE_HANDOFF entry, and short diff stats. Never include `.env`, secrets, or `reports/` contents in a bundle.

## Review etiquette

- Senior reviews land as `docs/SENIOR_CONSULTANT_REVIEW_<patch>_<date>.md` on a `review/*` branch so all agents can read them from git.
- Do not merge a patch that has a pending requested review unless Vadim explicitly waives it.
