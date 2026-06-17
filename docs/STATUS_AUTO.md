# Auto Status (machine-generated — do not hand-edit)

Generated: 2026-06-17T11:45:05Z
Main-tree HEAD: 73d922a P2-046I: wire Alpaca PAPER execution (fake money) + correct the safety model
Audit verdict: AUDIT_VERDICT=WARN

## Coinbase (live)
status=running  equity=59.4605  open_positions=1  daily_pnl=0.0
last_trade_at=None  last_loop_time=2026-06-14T09:52:14.114534-05:00  halt_reason=None

## Alpaca
status=running  equity=10.0  open_positions=0  last_loop_time=2026-06-16T13:05:51.671071-05:00

## Economics digest
cycles=54 wins=2 win_rate=3.7% cumulative_net_usd=-1.6117
recent_log_errors(last200 lines)=104

## Full audit snapshot
```
=== AUDIT SNAPSHOT 2026-06-17T11:44:57Z ===
=== GIT HEAD ===
73d922a P2-046I: wire Alpaca PAPER execution (fake money) + correct the safety model
2bea0ef P2-046G/H: performance tracking (equity curve) + gated Alpaca paper bridge
c1f5246 P2-046C: news as advisory + risk circuit-breaker (never a signal) + UI panel
7f11e6d P2-046F: add run_app.sh launcher (uses repo .venv; one-command app start)
5b31dcc P2-046F: runnable desktop app (pywebview) + paper executor, CLI-verified
27bdb74 P2-046D: app backend (config, portfolio store, planner service) + operator decisions
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
