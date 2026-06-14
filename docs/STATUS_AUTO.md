# Auto Status (machine-generated — do not hand-edit)

Generated: 2026-06-14T15:12:20Z
Main-tree HEAD: 1ae92a4 Add P2-043A Profit Thesis EV Contract
Audit verdict: AUDIT_VERDICT=WARN

## Coinbase (live)
status=running  equity=59.4605  open_positions=1  daily_pnl=0.0
last_trade_at=None  last_loop_time=2026-06-14T09:52:14.114534-05:00  halt_reason=None

## Alpaca
status=running  equity=10.0  open_positions=0  last_loop_time=2026-06-14T10:11:50.517095-05:00

## Economics digest
cycles=54 wins=2 win_rate=3.7% cumulative_net_usd=-1.6117
recent_log_errors(last200 lines)=44

## Full audit snapshot
```
=== AUDIT SNAPSHOT 2026-06-14T15:12:19Z ===
=== GIT HEAD ===
1ae92a4 Add P2-043A Profit Thesis EV Contract
25fb60c Add P2-042D high-volatility exploration strategy queue
7aeaf89 Add P2-042C research budget monitor and auto-kill decision layer
9bc9588 Add P2-042B live research evidence journal
556b966 Add P2-042A live research policy gate
66f49a0 Add P2-041D fee slippage replay scoring layer
=== LIVE P/L TRUTH (mode=live, action=EXIT) ===
cycles=54 wins=2 win_rate=3.7% cumulative_net_usd=-1.6117
=== EXIT REASONS (live) ===
  51 max hold time min (timeout)
   1 stop-loss hit @ 2016.1450 (stop=2018.3369)
   1 stop-loss hit @ 1762.0400 (stop=1762.6427)
   1 stop-loss hit @ 0.2001 (stop=0.2003)
=== NET BY STRATEGY (live EXIT) ===
mean_reversion         c=2 net=-0.0666
coinbase_probe         c=13 net=-0.0829
coinbase_exploration   c=26 net=-0.8141
recovered              c=13 net=-0.6482
=== ACTIVITY (last 3 live-EXIT days) ===
   1 2026-06-09
   2 2026-06-10
   1 2026-06-11
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
- WARN: 51/54 live exits are time-based (exit logic not fixed)
- WARN: win_rate 3.7% < 45% over 54 cycles
AUDIT_VERDICT=WARN
```
