# GROK / CODEX REVIEW GATE

**Purpose**: Reduce human copy/paste errors and long manual checklists for future Grok/Codex patches on this repo while keeping live trading risk at zero.

## Core Rules (both AIs and humans)

1. **Grok/Codex must run the local review gate** (or an equivalent manual checklist that produces the exact same compact report) on the review branch **before** emitting the final report for a patch.
2. **Grok/Codex never merges to main**. Only the human (or an explicit human-approved automation) may merge after reviewing the pasted report.
3. **Only the compact final report block is pasted back to ChatGPT**:
   - branch
   - base
   - head commit hash
   - changed files
   - tests/smokes run
   - protected-file result
   - read-only / risk statement
   - git status
   - "recommended next" line
4. The human pastes **only** that compact block (plus any preceding gate output the AI asked for). No raw `git diff`, no long terminal dumps unless the AI explicitly requests a specific section for investigation.
5. ChatGPT then performs the final merge-readiness decision using the pasted report + the patch's original constraints.

## How to Use (Grok/Codex)

```bash
python3 scripts/local_review_gate.py \
  --branch review/xxx-your-patch \
  --base main \
  --expected-file scripts/your_new_file.py \
  --expected-file tests/test_your_new_file.py \
  --expected-file docs/YOUR_DOC.md \
  --pytest tests/test_your_new_file.py -q \
  --py-compile scripts/your_new_file.py \
  --check-production-fill-logger
```

- Use `--allow-docs-active-handoff` **only** when the *entire* purpose of the patch is a live-status update to ACTIVE_HANDOFF.md (P2-014A style). Never for normal code patches.
- Add `--smoke "python3 scripts/foo.py --help"` for any new scripts.
- The gate is intentionally strict on protected files (`.env`, risk/strategy/runtime/launchd/config files, the fill logger CSV, etc.).

## Protected Defaults (always enforced)

See `PROTECTED_DEFAULTS` inside `scripts/local_review_gate.py`. They include:
- .env, logs/coinbase_fills.csv, logs/*, runtime/*, state/*, launchd/*
- config_coinbase_crypto.yaml
- strategy_crypto.py, main.py, broker_coinbase.py, order_manager.py, position_manager.py, risk_manager.py

Additional patterns can be passed with `--protected-file` or `--forbid-file`.

## Smart Fill Logger Protection (P2-014C improvement)

- `--check-production-fill-logger` scans **only non-test** changed `.py` files.
- It fails on actual call sites (`append_coinbase_fill_row(...)`).
- It **ignores** the string appearing inside tests that assert it is absent, inside the gate's own scanner logic, comments, or docstrings.
- It **always** fails if `logs/coinbase_fills.csv` (or equivalent) appears in changed files.
- This eliminates the previous false-positive where a broad grep caught the token inside a protective test.

## Future Use Cases (why this scaffolding exists)

- P2-014D and later open/orphan position + reconciliation status reports
- Future controlled fill-logger activation (when all direct broker facts are proven)
- Any Codex runtime/strategy patches after credit refresh (the gate + strict expected-file list makes drift obvious)

## One-Command Verification (recommended for humans/ChatGPT)

After the AI produces its "final report", the human (or the AI in a follow-up) can re-run the exact same gate command the AI used. If it passes cleanly and the compact report matches what was pasted, merge confidence is high.

## Do Not

- Do not run the gate and then ignore failures.
- Do not paste 800-line `git diff` outputs unless asked.
- Do not treat a green gate run as automatic merge permission — the human still decides.
- Do not update this doc or ACTIVE_HANDOFF.md as part of an unrelated patch.

This gate exists so we can increase review velocity without increasing operational or financial risk.

**Last updated**: P2-014C (gate introduction) — see the gate script itself for the authoritative implementation.
