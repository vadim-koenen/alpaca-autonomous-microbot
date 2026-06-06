# Spot-Check Protocol

**Principle:** data first, docs never, code by exception. Most checks read one screen of ground truth (the journal, config, git) — not the whole repo. A full code review is the expensive path, used only at decision points or when a tripwire fires.

## The tool
`scripts/audit_snapshot.sh` is read-only with respect to broker, runtime, and
trading behavior: no broker calls, no `.env`, and no orders. It prints a digest
and a final line `AUDIT_VERDICT=OK|WARN|CRITICAL` (exit code 0/1/2). It is not
strictly filesystem read-only: each execution stores the last cumulative net in
`reports/spot_checks/last_net.txt` to detect fresh bleeding between runs.

```bash
bash scripts/audit_snapshot.sh
```

## Tripwires
- **CRITICAL** — `coinbase_probe_enabled: true`; `max_trade_notional_usd > 10`; `max_open_positions > 1`; a paused strategy (`recovered`, `mean_reversion`, `coinbase_probe`) logging new live exits after the baseline date; cumulative net falling more than $1 since the last check.
- **WARN** — most live exits still time-based (exit logic unfixed); win rate < 45% over ≥20 cycles.

Update `BASELINE_DATE` in the script when a turnaround phase completes, so "new losses from a paused path" stays meaningful.

## Cadence
- **Background (automated):** daily run of the script (scheduled task `coinbase-bot-spot-check`). Logs every run; alerts on CRITICAL.
- **Manual quick check:** run the script anytime, or paste its output to Claude with "spot-check this against the turnaround plan."
- **Deep review (Claude crawls code):** only before re-enabling a live path, before any cap/scaling change, or when a tripwire fires.

## On CRITICAL
Open the latest `reports/spot_checks/audit_*.txt`, read the FINDINGS block, and fix the cause before the bot trades again. Pair with `docs/PROFIT_TURNAROUND_PLAN.md`.
