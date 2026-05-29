# Controlled Coinbase Exploration Runbook (P2-001)

## Overview

Controlled Exploration allows the bot to rotate micro-probes ($0.50-$1.00) across a broader set of approved symbols (BTC, ETH, SOL) to gather diverse live data for the Shadow Learner. This mode is explicitly opt-in and maintains strict risk gates.

## Risk Class

**Class 2.5: Controlled Live Behavior Change.** This mode increases trade frequency and symbol diversity but operates within hard-coded risk caps ($1.00 notional, 8 round trips/day, $3.00 daily stop loss).

## Configuration

In `config_coinbase_crypto.yaml`:

```yaml
crypto:
  controlled_exploration:
    enabled: true  # Set to true to opt-in
    approved_symbols:
      - BTC/USD
      - ETH/USD
      - SOL/USD
    max_single_trade_notional_usd: 1.00
    max_total_exploration_exposure_usd: 6.00
    max_round_trips_per_day: 8
    max_entries_per_symbol_per_day: 3
    per_symbol_cooldown_minutes: 45
    max_consecutive_losses: 3
    daily_stop_loss_usd: 3.00
    rotate_symbols: true
    avoid_same_symbol_repeat: true
```

## Behavior

1.  **Rotation**: The bot rotates through `approved_symbols`. It prefers symbols not recently traded.
2.  **Cooldown**: Each symbol has a mandatory 45-minute cooldown between exploration entries.
3.  **Risk Gates**:
    - **Exposure**: Total crypto exposure is capped at $6.00.
    - **Daily Loss**: Stop trading if daily realized loss reaches $3.00.
    - **Consecutive Losses**: Stop trading after 3 consecutive losing exits.
    - **Frequency**: Max 8 exploration round-trips per day; max 3 entries per symbol.
4.  **Logging**: Exploration trades are logged with `coinbase_exploration` strategy name and relevant shadow learner tags.

## Safety Monitoring

Run the safety report to verify the state and risk cap integrity:

```bash
python3 scripts/controlled_exploration_status.py
```

## Troubleshooting

- **No exploration trades**: Check if `enabled` is true and `LIVE_TRADING=true` in `.env`. Verify symbols have valid market data.
- **Blocked by cooldown**: Check `scripts/controlled_exploration_status.py` for "Recent Reject Reasons".
- **Risk caps violated**: The status script will flag if current config exceeds the P2-001 baseline.

## Related Tools

- `scripts/controlled_exploration_status.py`
- `strategy_crypto.py`
- `config_coinbase_crypto.yaml`
