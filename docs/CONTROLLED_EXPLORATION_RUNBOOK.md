# Controlled Coinbase Exploration Runbook (P2-001B)

## Overview

Controlled Exploration allows the bot to rotate micro-probes ($0.50-$1.00) across a broader set of approved symbols (BTC, ETH, SOL) to gather diverse live data for the Shadow Learner. This mode is explicitly opt-in and maintains strict risk gates.

**P2-001B Improvements**: 
- Rotation now uses **persisted journal history** instead of volatile in-memory state
- Automatically **avoids symbols with open positions**
- Avoids symbols on **per-symbol cooldown** using journal timestamps
- Enforces **max_entries_per_symbol_per_day** using journal history
- **Rotation survives bot restart** (no longer depends on in-memory index)

## Risk Class

**Class 2.0: Controlled Live Behavior Fix.** This fix improves symbol selection reliability by using persisted state, eliminating the risk of BTC-only repetition after restart.

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
    max_round_trips_per_day: 12
    max_entries_per_symbol_per_day: 4
    per_symbol_cooldown_minutes: 30
    max_consecutive_losses: 3
    daily_stop_loss_usd: 3.00
    rotate_symbols: true
    avoid_same_symbol_repeat: true  # ← Now actively used
    disable_legacy_btc_probe_when_enabled: true
```

## Behavior (P2-001B)

1.  **Intelligent Symbol Selection**: The bot selects exploration symbols using:
   - **Journal history**: Reads recent exploration entries to determine last-used timestamps
   - **Open position check**: Avoids symbols with active positions (uses state/coinbase/open_positions.json)
   - **Cooldown enforcement**: Respects per-symbol cooldown using journal timestamps (not in-memory)
   - **Daily entry limit**: Counts FILLED+PLACED entries per symbol in last 24h against max_entries_per_symbol_per_day
   - **Least-recently-selected**: Prefers symbols never seen before; then oldest timestamp

2. **Per-Symbol Cooldown**: Controlled exploration respects a mandatory cooldown between entries to the same symbol (default: 30 minutes), enforced via journal timestamps.

3.  **Risk Gates**:
    - **Exposure**: Total crypto exposure is capped at $6.00.
    - **Daily Loss**: Stop trading if daily realized loss reaches $3.00.
    - **Consecutive Losses**: Stop trading after 3 consecutive losing exits.
    - **Frequency**: Max 12 exploration round-trips per day; max 4 entries per symbol.
    
4. **Persistence**: 
   - Rotation state recovered from journal on every bot restart
   - Open positions read from state/coinbase/open_positions.json
   - Cooldown and entry counts tracked using journal CSV timestamps

5.  **Logging**: Exploration trades are logged with `coinbase_exploration` strategy name and relevant shadow learner tags.

## Safety Monitoring

Run the safety report to verify the state and risk cap integrity:

```bash
python3 scripts/controlled_exploration_status.py
```

Output will show:
- Controlled Exploration enabled/disabled status
- Risk cap integrity (vs P2-001B baseline)
- Recent activity (last 24h): daily trade count, per-symbol distribution
- Reject reasons (cooldown, open position, max entries, etc.)

## Troubleshooting

- **No exploration trades**: Check if `enabled` is true and `LIVE_TRADING=true` in `.env`. Verify symbols have valid market data.
- **All symbols rejected (open positions)**: Check `state/coinbase/open_positions.json`. Bot will not propose if position is open, but risk_manager will also reject downstream.
- **Blocked by cooldown**: Check `scripts/controlled_exploration_status.py` output for "Recent Reject Reasons". Each symbol has a 30-min (configurable) cooldown between exploration entries.
- **Max entries per symbol reached**: A symbol may have hit 4 entries in the last 24 hours. Wait for 24h window to roll over or reduce max_entries_per_symbol_per_day in config.
- **Risk caps violated**: The status script will flag if current config exceeds the P2-001B baseline (immutable).

## Bot Restart Safety

After a bot restart:
1. Strategy reads recent journal entries for the last timestamp per symbol
2. Selects next eligible symbol (not open, not on cooldown, not at max entries)
3. Prefers symbols that have NOT been selected recently
4. **Result**: Bot resumes rotation seamlessly, avoiding BTC-only repetition

## Related Tools

- `scripts/controlled_exploration_status.py` — Safety report
- `strategy_crypto.py` — Core selection logic
- `config_coinbase_crypto.yaml` — Configuration
- `state/coinbase/open_positions.json` — Open positions state
