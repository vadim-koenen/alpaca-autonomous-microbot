# Broker Read-Only Reconciliation And Alerting

## Purpose

P2-029C adds the operational evidence layer required before any Coinbase micro
trading recovery:

- captured broker facts versus local position state;
- file-based alerts and a dead-man heartbeat watchdog;
- atomic single-instance locking held for the process lifetime;
- a conservative recovery GO/NO_GO report.

It does not change entries, exits, symbols, sizing, risk caps, or strategy
thresholds.

## Broker Reconciliation Boundary

`scripts/coinbase_broker_readonly_reconciler.py` is fixture/captured-JSON first.
It does not instantiate `BrokerCoinbase`.

The current broker wrapper constructor loads credentials and performs an
immediate fee-rate request. That is too broad for an unattended reconciliation
command. Real broker access therefore remains disabled pending a dedicated
credential and read-only client review.

Offline example:

```bash
python3 scripts/coinbase_broker_readonly_reconciler.py \
  --json \
  --go-no-go-report \
  --broker-json tests/fixtures/coinbase_broker_readonly_reconcile/broker_ada_flat.json \
  --repo-root tests/fixtures/coinbase_manual_review_blocker_watchdog
```

The captured JSON may contain only:

- `broker_query_succeeded`
- balances by asset
- open orders by product/symbol

The report never accepts local journal estimates as broker truth.

## Symbol Classifications

Each of ADA/USD, SOL/USD, BTC/USD, and ETH/USD receives one classification:

- `local_open_broker_flat`
- `local_open_broker_open`
- `local_flat_broker_open`
- `local_external_inventory_only`
- `unknown`

SOL external/staked inventory remains separate from bot-owned open positions.

ADA becomes a clear candidate only when:

1. local ADA is a manual-review blocker;
2. captured broker reconciliation succeeded;
3. direct broker balance evidence reports zero ADA;
4. direct broker order evidence reports no ADA open order.

The report does not clear state. It may only direct the operator to the guarded
P2-029B command.

## File Alerts

`scripts/bot_alerts.py` exposes:

```python
alert(level, message, context)
```

It writes:

- `reports/alerts/alerts.jsonl`
- `reports/alerts/alerts.log`

Secret-like context keys and inline values are redacted. Email is not active in
this patch; callers receive `email_status=email_not_configured`. This avoids
creating a second credential-loading path.

## Heartbeat And Dead-Man Watchdog

Default mode is report-only:

```bash
python3 scripts/bot_heartbeat_watchdog.py --json
```

Enable local file alerts explicitly:

```bash
python3 scripts/bot_heartbeat_watchdog.py --json --emit-alerts
```

It detects:

- heartbeat missing or older than 10 minutes;
- manual-review blocker older than 15 or 30 minutes;
- duplicate live processes;
- stale runtime lock;
- no completed round-trip exit in 24 hours;
- failed close warning in the journal;
- `STOP_TRADING` present while a live process remains;
- live process without a valid lock or fresh heartbeat.

It never kills, restarts, clears state, or calls the broker.

## Atomic Single-Instance Lock

The live process lock now uses `fcntl.flock(... LOCK_EX | LOCK_NB)` on a stable
hidden guard inode and retains the open file descriptor for the process
lifetime. The existing broker PID lock file remains operator-readable.

- An active owner cannot be displaced, including with `--force-lock`.
- Stale PID text without an active OS lock can be recovered.
- The live loop verifies that its held descriptor still matches the on-disk
  lock inode and current PID.
- Lost ownership stops further live cycles before account refresh or order
  evaluation and emits a CRITICAL file alert.
- `--force-lock` is recorded as a CRITICAL audit warning and only succeeds when
  the OS lock is actually available.

No lock file should be removed manually.

## GO/NO_GO Gates

`resume_micro_trading_go_no_go=GO` requires:

- captured broker query succeeded;
- ADA balance and open orders are confirmed absent;
- local ADA is absent or eligible for guarded local cleanup;
- no duplicate live process;
- lock health is `OK`;
- heartbeat is fresh;
- local file alerting is active;
- `max_open_positions` remains `1`;
- existing trade caps remain unchanged by this report.

Even a GO report preserves:

```text
broker_order_authorized=false
live_trading_authorized=false
state_clear_authorized=false
scaling_authorized=false
strategy_change_authorized=false
```

GO is evidence readiness for an operator decision, not permission to trade.

## Required Future Work

After this patch is merged:

1. Review and isolate a credential-safe Coinbase balances/open-orders client.
2. Capture direct broker facts through an explicitly approved read-only command.
3. Run the GO/NO_GO report.
4. Clear ADA only if direct broker facts show no exposure and no open order.
5. Schedule file alerting/dead-man execution.

Do not resume live micro trading before these gates are satisfied.
