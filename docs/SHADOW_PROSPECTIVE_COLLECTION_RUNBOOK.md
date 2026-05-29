# Shadow Prospective Collection Runbook

This workflow collects advisory-only shadow learner samples. It does not change
live trading behavior, risk approvals, sizing, symbol selection, strategy logic,
or broker orders.

## Purpose

Run the shadow collection cycle daily after enough new scan/log activity exists:

1. Check bot readiness from read-only status/reconcile/preflight outputs.
2. Ingest new log/state observations into shadow learner tables.
3. Refresh public read-only price coverage for symbols already present in the shadow DB.
4. Label expired shadow prediction horizons.
5. Report prospective, retrospective, and original scan-time samples separately.
6. Evaluate prospective shadow samples with a separate paper gate.
7. Write a daily advisory summary under `reports/`.

## Commands

Dry-run first:

```bash
python3 scripts/shadow_collect_cycle.py --since 2026-05-28 --dry-run
```

Write cycle:

```bash
python3 scripts/shadow_collect_cycle.py --since 2026-05-28
```

Prospective-only cycle output:

```bash
python3 scripts/shadow_collect_cycle.py --since 2026-05-28 --prospective-only
```

## Readiness Blockers

Stop before ingestion if any of these appear:

- stale heartbeat
- duplicate bot process indicator
- nonzero manual-review open count
- nonzero broker-recovered open count
- active ETH recovery churn
- `STOP_AND_REVIEW`

Warnings from active runtime indicators or a missing `state/alpaca/closed_positions.json`
do not by themselves authorize cleanup. Only run state initialization with bots stopped
and explicit human approval.

## Paper Gate

Paper validation remains blocked unless all are true:

- at least 2 separate prospective collection days
- at least 100 labeled prospective directional outcomes
- at least 30 labeled prospective outcomes in one symbol/horizon/model bucket
- prospective non-random model beats prospective random baseline materially
- missing-data bias is reported
- no safety/preflight blocker exists

The cycle may report `PAPER_GATE_READY_FOR_REVIEW`, but it must never report
approval for paper trading or live trading.

## Safety Notes

- No launchctl.
- No restart.
- No live mode.
- No broker order commands.
- No authenticated broker account/order APIs.
- No `.env` reads or edits.
- No strategy, risk, sizing, cap, exposure, or Coinbase `dead_chop` changes.
- Shadow learner output remains advisory-only.
