# Coinbase Live Readiness Runbook

**Purpose**: Operational guide for using the zero-network `coinbase_live_readiness_diagnostic.py` to determine when it is safe and useful to run the read-only live broker probe.

## When to Use This

Before every attempt to run:

```bash
python3 scripts/coinbase_live_broker_reconciliation_probe.py --live-read-only --json
```

Always run the readiness diagnostic first:

```bash
python3 scripts/coinbase_live_readiness_diagnostic.py
python3 scripts/coinbase_live_readiness_diagnostic.py --json
```

## What the Diagnostic Tells You

- `verdict`: BLOCKED / READY_WITH_CAUTION / READY
- Boolean presence of `COINBASE_API_KEY` and `COINBASE_API_SECRET` (redacted)
- Whether the Coinbase client and `BrokerCoinbase` can be imported
- Whether the constructor still carries legacy `dry_run` expectations (from P2-015B we know it does not)
- Whether the live probe script itself exists
- A clear `recommended_next_action`

## Transition Criteria to Live Probe

Only proceed with `--live-read-only` when the diagnostic shows:

- Both key booleans are true
- Client and broker are importable
- No obvious adapter blocker in the signature check
- The recommended action explicitly supports running the live probe

## After a Live Probe Run

Re-run the readiness diagnostic afterward if you want to confirm the environment is still correctly configured for future probes.

## Relationship to Other Runbooks

- Use `COINBASE_READ_ONLY_CREDENTIAL_SETUP_RUNBOOK.md` for the actual credential creation and `.env` hygiene steps.
- Use the live probe's own output + this readiness diagnostic for day-to-day operational decisions.
- Never use this as an excuse to relax risk gates or attempt trading changes.

This runbook exists to make the "move from BLOCKED (credentials) → one clean live truth check" process repeatable and auditable without leaking secrets or increasing operational risk.

---
*Created as part of P2-016C docs cleanup. Pair with the readiness diagnostic and credential setup runbook.*