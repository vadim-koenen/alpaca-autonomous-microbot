# P2-035A: Operational Net Alerts

## Goal
Establish a reliable, read-only dead-man layer that acts independently of the main trading loop to detect application hangs, crashes, or stale state without mutating trading context or order state. It enables secure, local desktop alerting for operational visibility.

## Scope
* **main.py**: Integrates `loop_count` into `_write_heartbeat` to surface exact trading loop progression.
* **bot_heartbeat_watchdog.py**: Extends read-only diagnostics to evaluate:
  * **Heartbeat Freshness**: Detects if the loop has stalled based on timestamp.
  * **Loop Progression**: Uses local untracked `runtime/watchdog_state.json` cache to determine if timestamp changed but `loop_count` remains stuck (silent loop spin).
  * **Lock Integrity**: Validates presence of `coinbase.lock` and compares process ID against active snapshots.
* **bot_alerts.py**: Implements secure dispatch to `osascript` (macOS native notifications) with forced redactions of sensitive data (e.g., keys, UUIDs, numeric IDs) and a dry-run default posture (`ENABLE_MACOS_ALERTS=1`).
* **tests**: Comprehensive coverage added to `tests/test_p2_035a_operational_net_alerts.py` to assert correct execution paths, test redactions, and evaluate backward compatibility.

## Implementation Details

### Subprocess Safety
Standard `subprocess.run` usage was introduced strictly for dispatching macOS notifications. Parameters are safe (`shell=False`, `timeout=5`), and arguments are dynamically sanitized before dispatch.

### Redaction Strategy
Account IDs, tokens, keys, and UUIDs within dictionary state or strings are filtered prior to string representation in notifications. 

### Backward Compatibility
State cache tests tolerate missing values (e.g., initial run without previous state or heartbeat missing `loop_count`) safely.

## Deployment Notes
* State caching relies on `runtime/watchdog_state.json`, which must not be committed to source control (added to `.gitignore`).
* Alerts trigger via macOS Notifications only when `ENABLE_MACOS_ALERTS=1` is provided to the run environment. Otherwise, they silently emit to the log.
