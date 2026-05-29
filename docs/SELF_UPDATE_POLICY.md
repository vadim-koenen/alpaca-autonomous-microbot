# Self-Update Policy

The live trading process must never self-modify.

The bot may recommend patches, write diagnostics, and prepare reviewable
proposals, but it may not auto-deploy trading, risk, broker, or strategy changes.

## Change Classes

Class 0 changes cover docs, comments, tests, read-only diagnostics, and summary
formatting. They may be proposed automatically, but they are still reported.

Class 1 changes cover logging, reconciliation output, memory writes, heartbeat
improvements, and secret-safe diagnostics. They may be proposed automatically,
but they are still reported.

Class 2 changes cover risk manager, order manager, position manager, broker
adapters, exposure calculation, and stop-loss or take-profit behavior. Class 2
changes require human approval before deployment.

Class 3 changes cover strategy expansion, new symbols, larger sizing, higher
exposure caps, margin, shorting, options, leverage, staking or lockups, and
automated transfers. Class 3 changes require explicit human approval and a
separate risk review.

## Deployment Boundary

No auto-deploy exists yet.

Rollback and restart remain human-controlled. The bot may recommend a rollback
or restart checklist, but it must not perform launchd start/stop/load/unload or
modify the running live process without explicit human action.

The live trader executes only approved code and approved config. Research,
recommendation, memory, and patch-preparation components must not have authority
to place orders or deploy themselves into live trading.
