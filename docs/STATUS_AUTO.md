# Auto Status (machine-generated — do not hand-edit)

Generated: 2026-06-09T12:57:29Z
Main-tree HEAD: f3d8afe P2-035: free status sync + GPT working agreement + reviews
Audit verdict: AUDIT_VERDICT=WARN

## Coinbase (live)
status=running  equity=59.8793  open_positions=0  daily_pnl=-0.0619
last_trade_at=2026-06-09T03:54:00.279679Z  last_loop_time=2026-06-09T07:56:44.524673-05:00  halt_reason=None

## Alpaca
status=running  equity=10.0  open_positions=0  last_loop_time=2026-06-09T07:57:05.500132-05:00

## Economics digest
cycles=51 wins=1 win_rate=2.0% cumulative_net_usd=-1.4405
recent_log_errors(last200 lines)=0

## Full audit snapshot
```
=== AUDIT SNAPSHOT 2026-06-09T12:57:27Z ===
=== GIT HEAD ===
f3d8afe P2-035: free status sync + GPT working agreement + reviews
6cd49fe Add P2-035 Claude senior review + GPT roadmap
f903731 auto: handoff sync 2026-06-08 17:04
2ac2df9 Add P2-034B broker readonly evidence handoff
85f889c auto: handoff sync 2026-06-08 09:01
6c9be2c Add P2-032C dashboard runtime truth panel
=== LIVE P/L TRUTH (mode=live, action=EXIT) ===
cycles=51 wins=1 win_rate=2.0% cumulative_net_usd=-1.4405
=== EXIT REASONS (live) ===
  48 max hold time min (timeout)
   1 stop-loss hit @ 2016.1450 (stop=2018.3369)
   1 stop-loss hit @ 1762.0400 (stop=1762.6427)
   1 stop-loss hit @ 0.2001 (stop=0.2003)
=== NET BY STRATEGY (live EXIT) ===
mean_reversion         c=2 net=-0.0666
coinbase_probe         c=13 net=-0.0829
coinbase_exploration   c=23 net=-0.6428
recovered              c=13 net=-0.6482
=== ACTIVITY (last 3 live-EXIT days) ===
   2 2026-06-03
   1 2026-06-04
   1 2026-06-09
=== RISK CONFIG ===
  max_open_positions: 1
  min_trade_notional_usd: 5.00
  max_trade_notional_usd: 10.00
  stop_loss_pct: 1.50
  take_profit_pct: 3.00
    max_single_trade_notional_usd: 10.00
  coinbase_probe_enabled: false
  coinbase_probe_notional_usd: 0.50
  coinbase_probe_stop_loss_pct: 1.50
  coinbase_probe_take_profit_pct: 3.25
  # daily_stop_loss_pct / max_exposure_pct helpers are ADVISORY (not live risk gates).
  # Trade size never exceeds controlled_exploration.max_single_trade_notional_usd.
    min_notional_usd: 5.00
    max_notional_usd: 10.00
    daily_stop_loss_pct: 7.5
  # Micro-size only: new symbols use the *existing* max_trade_notional_usd / min_trade_notional_usd.
    # Pilot-size: uses existing max_trade_notional_usd (10.00). Exposure/daily loss capped at BTC/ETH-only pilot limits.
=== FINDINGS ===
- WARN: 48/51 live exits are time-based (exit logic not fixed)
- WARN: win_rate 2.0% < 45% over 51 cycles
AUDIT_VERDICT=WARN
```
