# Coinbase Read-Only Credential Setup Runbook

**Purpose**: Enable a successful, safe, read-only broker truth probe (`--live-read-only`) without ever exposing secrets in transcripts, commits, or AI conversations.

## Strict Safety Rules (Non-Negotiable)

- **Never paste secrets** into ChatGPT, Grok, Codex, any terminal transcript, or any AI conversation.
- Credentials must be **read-only / no trade / no transfer / no withdrawal** permissions only.
- `.env` (or equivalent) must stay **local and uncommitted** (already in `.gitignore`).
- This runbook is for **readiness verification only**. It does not grant trading rights.

## Expected Environment Variables

The readiness diagnostic and live probe expect (at minimum):

- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`

`COINBASE_PASSPHRASE` is reported for completeness but is typically **not required** for the current Advanced Trade REST client used by this repo.

## Recommended Local Setup (Never commit secrets)

1. Ensure you have a dedicated Coinbase Advanced Trade API key pair with **read-only** permissions.
2. Store them locally only:

   ```bash
   # In your local .env (never committed)
   COINBASE_API_KEY=your_readonly_key_here
   COINBASE_API_SECRET=your_readonly_secret_here
   ```

3. Load them into your shell environment for the current session (or use your existing `.env` loader if the repo scripts already support it for diagnostics).

## Verification Steps (Safe, Redacted)

Run the zero-network diagnostic first:

```bash
python3 scripts/coinbase_live_readiness_diagnostic.py
python3 scripts/coinbase_live_readiness_diagnostic.py --json
```

Expected safe output (redacted booleans only):

- `has_coinbase_api_key: true`
- `has_coinbase_api_secret: true`
- `network_calls_made: false`
- `broker_calls_made: false`
- `recommended_next_action: ...` (should indicate readiness for live probe)

Only proceed to the live probe **after** the diagnostic reports sufficient readiness.

## Running the Live Read-Only Probe

```bash
python3 scripts/coinbase_live_broker_reconciliation_probe.py --live-read-only --json
```

**Interpretation Rules** (critical):

- If `broker_read_successful != true` → Broker truth is **not established**. Do **not** treat `sol_on_broker` or `eth_on_broker` as false.
- `sol_on_broker: null` or `eth_on_broker: null` means **unknown**, not "clear / not held".
- If the broker reports SOL or ETH holdings:
  - Do **not** automatically close positions.
  - Prepare a separate, human-reviewed remediation plan.
- No P/L or outcome aggregation is safe until:
  - Direct broker fills/proceeds/fees are proven (see P2-014B series).
  - Orphan/dropped position blockers are resolved with evidence.

## What To Do If Credentials Are Missing

1. Create a new dedicated read-only API key pair in the Coinbase Advanced Trade portal.
2. Restrict permissions to read-only.
3. Store locally in `.env` (uncommitted).
4. Re-run the readiness diagnostic.
5. Only then attempt the single live probe with `--live-read-only`.

## Common Pitfalls to Avoid

- Using keys with trade/withdrawal permissions for diagnostics.
- Committing `.env` or any file containing keys.
- Sharing keys in any AI prompt or chat.
- Running the live probe repeatedly without first confirming readiness (wastes rate limits and creates noise).

This runbook exists so the operator can move from "BLOCKED (credentials missing)" to "ready for one clean live broker truth check" with zero risk of secret leakage or accidental trading behavior.

---
*Created as part of P2-016C docs cleanup. Use with the live readiness diagnostic and probe only.*