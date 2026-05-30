# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

# Coinbase Exit Quality Report Runbook — P2-001E

## Overview

The Coinbase Exit Quality Report (`scripts/coinbase_exit_quality_report.py`) is a read-only diagnostic tool that analyzes exit behavior from the live controlled exploration trading bot. It answers critical questions about whether your exit thresholds (TP/SL/hold-time) are effective.

**Risk Class:** Class 1 advisory/read-only — no live trading modifications.

---

## Quick Start

```bash
# 1. Run the report
python3 scripts/coinbase_exit_quality_report.py

# 2. Run unit tests (recommended after any local development)
python3 -m pytest tests/test_coinbase_exit_quality_report.py -v

# 3. Validate syntax
python3 -m py_compile scripts/coinbase_exit_quality_report.py
```

---

## What It Analyzes

### 1. Exit Type Distribution
- **max_hold**: Time-based exits when 90-min hold window expires
- **stop_loss**: Triggered by hitting -1.5% loss threshold (if ever triggered)
- **take_profit**: Triggered by hitting +3% gain threshold (if ever triggered)
- **other**: Manual or unknown exit reasons

Each type includes:
- Count and percentage of total exits
- Average net P/L per exit
- Total fees paid for that exit type
- Win rate (count of positive P/L exits)

**Key question answered:** Are SL/TP thresholds even being hit, or are all exits time-based?

### 2. Fee Impact Analysis
- Total fees paid across all exits
- Average fee per exit
- Total net P/L (all exits combined)
- Overall win rate

**Key question answered:** How much does fee drag eat into your profits?

### 3. Maximum Favorable / Adverse Excursion (MFE/MAE) Analysis
- **MFE**: Average and max favorable price movement from entry to exit (profitable direction)
- **MAE**: Average and max adverse price movement from entry to exit (losing direction)
- Measured as percentage change from fill_price to exit_price (assuming Long)

**Limitations:**
- Only sees realized move at the moment of exit
- Does NOT include intraday high/low during hold window
- To analyze true MFE/MAE, would need intratrade price path (from broker historical bars)

**Key question answered:** When you exit, how far did price actually move in your favor vs against you?

### 4. Hold-Time Analysis
- Parses hold times directly from journal reason strings if available (e.g., "(90.6min held)")
- Computes average, min, and max hold times
- Explains data limitations if exact hold times cannot be computed

**Key question answered:** What is the actual average hold time of your trades?

### 5. Trades Within 50% of 3% TP Threshold
- Counts exits where pnl_pct >= 1.5% (which is 50% of the 3% TP threshold)
- Indicates how often price gets close to your TP target

**Key question answered:** Are trades approaching your TP, or is the threshold unrealistic?

### 6. TP/SL Threshold Simulation
- Estimates how many exits would have triggered a 1.5% stop-loss
- Uses pnl_pct as proxy for price movement (limited by fee inclusion)

**Limitations:**
- pnl_pct includes fees, so cannot simulate gross thresholds
- Would need price path to simulate more accurately

**Key question answered:** Would stricter SL thresholds have prevented some losses?

### 7. Per-Symbol Breakdown
For each symbol (BTC/USD, ETH/USD, SOL/USD, etc.):
- Total exits and net P/L
- Average P/L per exit
- Win rate
- Distribution of exit types

**Key question answered:** Do different symbols have different exit quality patterns?

### 8. Advisory Recommendations
- High-level suggestions based on observed patterns
- **No configuration changes recommended** — requires human review

---

## Output Format

```
================================================================================
COINBASE EXIT QUALITY REPORT — P2-001E
================================================================================
Generated: <timestamp>
Total exits analyzed: 33

────────────────────────────────────────────────────────────────────────────────
1. EXIT TYPE DISTRIBUTION
────────────────────────────────────────────────────────────────────────────────
  MAX_HOLD        | Count:  33 (100.0%) | Avg P/L: $-0.001234 | ... | Winning: 10/33
  
  ⚠️  WARNING: 100% of exits are max_hold exits.
     SL/TP thresholds (1.5%/3%) have NEVER triggered in this sample.

────────────────────────────────────────────────────────────────────────────────
2. FEE IMPACT ANALYSIS
────────────────────────────────────────────────────────────────────────────────
  Total fees paid:           $0.234567
  Average fee per exit:      $0.007107
  Total net P/L (all exits): $-0.123456
  Win rate:                  10/33

[... more sections ...]

================================================================================
END REPORT
================================================================================
```

---

## Data Sources (Priority Order)

The report searches for journal data in this order:

1. `journal_coinbase_crypto.csv` (primary)
2. `logs/coinbase_journal.csv` (fallback)
3. `journal.csv` (legacy fallback)

The first file found is used. If none exist, the report fails with an error.

---

## Fields Used from Journal

| Field | Used For | Notes |
|-------|----------|-------|
| `timestamp` | Record ordering | ISO 8601 format |
| `symbol` | Per-symbol breakdown | BTC/USD, ETH/USD, SOL/USD, etc. |
| `action` | Filter to exits only | Only EXIT records analyzed |
| `status` | Filter to completed exits | Only PLACED or FILLED |
| `reason` | Exit type classification | Text-based pattern matching |
| `fill_price` | MFE calculation | Entry price |
| `exit_price` | MFE and P/L verification | Exit price |
| `pnl_usd` | P/L analysis | Net P/L in dollars |
| `pnl_pct` | % return analysis | TP/SL threshold simulation |
| `fees_paid` | Fee impact | Total fees for this exit |
| `gross_pnl` | Verification | Gross before fees |

---

## Common Findings

### "100% of exits are max_hold"
This means SL/TP thresholds have never triggered. Possible causes:
- Thresholds are too tight for the volatility regime
- Hold window is too short to reach typical move sizes
- Market is in low-volatility regime

**Next step:** Study whether thresholds should be widened, or if shorter holds + lower thresholds are better.

### "Average fee per exit > average profit per exit"
Fee drag is dominant. At $1 notional with 1.2% taker fee round-trip, you need ~2.4% gross move to break even.

**Next step:** Either increase notional (to reduce fee impact %), or focus on higher-conviction entries.

### "Win rate < 30%"
More losing trades than winning. Combined with fee drag, this is likely unprofitable.

**Next step:** Consider whether entry signal needs improvement, or if market regime is unfavorable.

---

## Limitations and Caveats

### Price Path Data
- Journal only stores fill_price and exit_price
- Cannot see if price hit higher/lower intraday
- MFE analysis is limited to realized move from entry to exit
- **Workaround:** Extract broker OHLC data for the hold window

### Entry Timestamps
- Journal has exit timestamps but not entry timestamps in a usable format for hold-time studies
- Cannot compute exact hold duration for each trade
- Cannot compare 45-min vs 90-min exit quality
- **Workaround:** Parse broker order fills and match by order_id

### Fee Inclusion in pnl_pct
- TP/SL simulation uses pnl_pct which includes fees
- Cannot simulate "what if SL was 2% gross" without knowing fees
- **Workaround:** Split gross_pnl and fees_paid to reconstruct gross move

### Small Sample
- At current $1 notional + limited trading hours, sample size is small
- 33 exits is not enough for high statistical confidence
- Results should guide hypothesis, not replace larger-scale testing

---

## How to Interpret Recommendations

**Do NOT immediately change config based on this report.** Instead:

1. **Read the report carefully.** Understand which symptoms are present.
2. **Cross-check with other data.** Are fees really dominant? Are TP/SL truly ineffective, or just unlucky?
3. **Form a hypothesis.** E.g., "45-min hold might reduce fee impact while capturing upside."
4. **Design a test.** E.g., "Run 20 trades with 45-min hold, measure win rate."
5. **Get human review.** Discuss findings with team before changing config.
6. **Change incrementally.** One variable at a time (SL OR TP OR hold-time, not all three).

---

## Do NOT Change

- `config_coinbase_crypto.yaml` (holds risk caps, notional, exposure limits)
- `.env` (holds API keys)
- `main.py`, `broker_*.py`, `order_manager.py`, `risk_manager.py` (live trading logic)
- `launchd/` (bot startup configuration)
- `state/` (bot state persistence)

This report is **read-only analysis only**. Its recommendations are advisory.

---

## Testing

The report includes comprehensive unit tests:

```bash
python3 -m pytest tests/test_coinbase_exit_quality_report.py -v
```

Tests cover:
- Exit type classification (max_hold, stop_loss, take_profit, other)
- P/L averaging by exit type
- Per-symbol breakdown
- 100% max_hold detection
- MFE calculation
- Trades within 50% of TP threshold
- SL trigger simulation
- Empty/no-data handling
- Invalid numeric field handling
- **Forbidden import check** (no broker/order_manager/risk_manager imports)

---

## Troubleshooting

### "No journal found"
- Check that `journal_coinbase_crypto.csv` exists in repo root
- Verify file is not corrupted (try `head -5 journal_coinbase_crypto.csv`)
- Check file permissions (should be readable)

### "No exit records found"
- Journal exists but has no EXIT rows
- This is OK if bot has not yet completed any trades

### Exit counts don't match
- Journal may have both ALGO/USD and BTC/USD rows
- Report only analyzes rows where `action == 'EXIT'` and `status` is PLACED or FILLED
- Verify manually: `grep ",EXIT," journal_coinbase_crypto.csv | wc -l`

### MFE values seem wrong
- MFE is computed as `(exit_price - fill_price) / fill_price * 100`
- For a losing trade, this will be negative (price moved against you)
- This is correct and expected

---

## Next Steps (After Review)

### Phase 1: Gather More Data
- Run for 100+ cycles per symbol to improve statistical confidence
- Extract intratrade high/low from broker for true MFE analysis
- Pair entry/exit timestamps from order fills

### Phase 2: Hypothesis Testing
- Test 45-min hold vs 90-min hold on same signal
- Test tighter SL (2% vs 1.5%) on subset of trades
- Test wider TP (5% vs 3%) on subset of trades

### Phase 3: Incremental Config Changes (Requires Approval)
- After testing confirms improvement, change ONE variable in config
- Monitor for 50+ trades to confirm improvement holds
- Document change and results in ACTIVE_HANDOFF.md

---

## Related Documents

- [ACTIVE_HANDOFF.md](./ACTIVE_HANDOFF.md) — Live bot state, handoff protocol
- [Controlled Exploration Status](./scripts/controlled_exploration_status.py) — Real-time bot status
- [P2-001C Fee/Performance Report](./scripts/coinbase_exploration_fee_performance_report.py) — Earlier fee analysis

---

**Last Updated:** 2026-05-30 (P2-001E implementation)  
**Author:** Claude (advisor) + Copilot (implementation)  
**Status:** ACTIVE — Advisory analysis in production use.
