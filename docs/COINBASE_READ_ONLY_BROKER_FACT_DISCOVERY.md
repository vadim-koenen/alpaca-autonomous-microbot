# P2-011J — Read-Only Coinbase Broker-Fact Discovery Probe

**Status:** Pure discovery / proof. No logger writes. No order actions. No default live behavior changes.

## What Was Added

- `scripts/coinbase_read_only_broker_fact_probe.py`
- `tests/test_coinbase_read_only_broker_fact_probe.py`
- `docs/COINBASE_READ_ONLY_BROKER_FACT_DISCOVERY.md` (this file)

No changes were made to any live trading, strategy, risk, position_manager (beyond what was already there from P2-011H), config, .env, LaunchAgents, or runtime files.

## Purpose

This patch provides a safe, read-only tool to answer the question:

> "What direct broker facts can we actually see from Coinbase today using only read surfaces?"

It is the logical continuation of the P2-011E–I series:
- P2-011E proved we can call historical fills in an inert way.
- P2-011F/G gave us pure reconciliation and capture helpers.
- P2-011H/I gave us an opt-in dry-run seam inside the real flow and a controlled probe.

P2-011J focuses on **field-presence discovery** at the broker surface level, with strong redaction and an explicit "live read only" opt-in.

## Safety Model

- Default execution: 100% synthetic / fixture-driven. Zero network calls.
- Live reads: only possible with the explicit `--live-read-only` CLI flag.
- When producing human-readable output from live data, all sensitive values (account UUIDs, client_order_ids that could leak strategy, etc.) are redacted.
- The probe never writes to `logs/coinbase_fills.csv` and never calls `append_coinbase_fill_row`.
- No POST/PUT/PATCH/DELETE or order submission paths are present or callable.

## Core Capabilities

Pure parsing helpers that report **presence**, not values:

- `analyze_broker_facts(order_status, historical_fills, ...)` → `BrokerFactDiscoveryReport`
- Clear `OrderFactSummary` and `FillFactSummary` objects.
- `logger_readiness_blocked` + `blocking_reasons` exactly as required by the series.

The report distinguishes:
- direct_broker_fact present
- missing
- unsafe_to_infer (never guesses)

## Usage (Safe by Default)

```bash
# Pure synthetic mode (recommended for normal use and CI)
python3 scripts/coinbase_read_only_broker_fact_probe.py

# Optional controlled live discovery (you must opt in)
python3 scripts/coinbase_read_only_broker_fact_probe.py \
  --live-read-only \
  --symbol BTC-USD \
  --order-id <some-order> \
  --output json
```

## Relationship to Readiness for Logging

The probe will correctly report `logger_readiness_blocked=True` (with reasons) unless **all** of the following are directly present from broker data:

- Direct sell proceeds (`filled_value` on SELL/close orders)
- Stable per-fill IDs on the fills associated with those orders
- Per-fill fees
- End-to-end coverage for both entry and exit legs

As of P2-011J, these conditions are still not met for production exits in the current controlled-exploration setup. Therefore the logger hook remains blocked.

## Verification Performed

- All new and previous Coinbase-related tests pass.
- `git diff --check` clean.
- Explicit greps confirm no new write paths, no calls to `append_coinbase_fill_row` outside test patching, and `ACTIVE_HANDOFF.md` untouched on this branch.
- Default execution performs zero live reads.

---

P2-011J complete. Read-only broker-fact discovery probe added. Logger hook remains blocked. All hard constraints respected.
