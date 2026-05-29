# Releases

## v0.1.0-safety-baseline

Safety baseline for the Alpaca/Coinbase microbot.

This baseline means:

- ETH broker-recovered blocking state has a documented resolution path.
- `RISK_CONFIG` startup logging is present.
- Broker-recovered positions skip exit evaluation unless explicitly made controllable.
- Aggregate Alpaca exposure cap is enforced before order approval.
- Duplicate-order intent guard is present.
- Self-update scaffold is advisory only.
- No auto-deploy exists.
- Test suite is expected to remain at 158+ passing tests.

Release snapshots are local artifacts only. They do not deploy, restart, or
modify live trading processes.
