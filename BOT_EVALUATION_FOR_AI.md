# Alpaca Autonomous Crypto Micro-Bot — Evaluation Brief

*Share this file with any AI assistant to get a full-context code review and improvement suggestions.*

---

## 1. What This Bot Is

A fully autonomous, rule-bound crypto trading bot running **live on Alpaca/Coinbase** with a ~$10 account. It scans 5 crypto symbols every loop, proposes trades through three strategies, passes every proposal through a mandatory risk manager, and manages open positions (stop-loss, take-profit, max hold time). It also supports paper and dry-run modes for safe testing.

**Primary constraint:** profitability must come from better strategy logic — NOT from loosening risk rules or safety limits.

---

## 2. Hard Rules (These Cannot Change)

- API keys stored only in `.env`, never printed or exposed
- `LIVE_TRADING=true` env var required for any live order
- Risk manager is authoritative — strategies only propose, risk manager decides
- No crypto margin, no short selling (Coinbase doesn't support it)
- Max trade: **$2.00** | Max total exposure: **$4.00** | Max daily loss: **$2.00**
- Equity floor: **$1.50** — live trading halts below this
- Stop after **2 consecutive losses** per session
- Max **5 trades per day**
- Max **4 open positions** at once
- All trades need a stop-loss AND take-profit before they're allowed
- Process lock prevents duplicate live instances
- Kill switch file (`runtime/STOP_TRADING`) halts the bot immediately
- 73 unit tests must continue to pass after any change

---

## 3. Architecture Overview

```
main.py (main loop, ~90s cycle)
  ├── permissions.py      — queries broker for account eligibility at startup
  ├── strategy_router.py  — dispatches to CryptoStrategy per symbol
  │     └── strategy_crypto.py  — 3 strategies, each returns a TradeProposal or None
  ├── risk_manager.py     — 20+ deterministic checks; blocks or approves proposals
  ├── order_manager.py    — places approved orders; updates session state
  ├── position_manager.py — monitors open positions; triggers exits; calculates net P&L
  ├── journal.py          — writes every action to journal.csv (with fees)
  ├── broker_alpaca.py    — Alpaca API wrapper (paper + live)
  ├── market_data.py      — quotes, OHLCV bars, indicator calculations
  └── utils.py            — config, process lock, kill switch, state persistence
```

**Modes:** `dry_run` → `paper` → `live` (live requires `LIVE_TRADING=true`)

---

## 4. Trading Symbols

`BTC/USD`, `ETH/USD`, `SOL/USD`, `DOGE/USD`, `ALGO/USD`

---

## 5. The Three Strategies (strategy_crypto.py)

All three are **long-only** (Coinbase doesn't support shorts). Each strategy:
1. Fetches a live quote and 20-bar OHLCV history (5-minute bars)
2. Computes indicators (RSI-14, EMA-9/21, SMA-20, Bollinger Bands, relative volume, momentum)
3. Scores a confidence (0–1); requires ≥ 0.65 to propose
4. Computes notional: `min(max_trade=$2, buying_power × 0.85)`
5. Attaches fee metadata (entry + exit fees, spread, slippage, net expected edge)
6. Returns a `TradeProposal` or `None`

### 5a. Momentum Breakout
**Signal:** Price closes above the 20-bar high + relative volume > 1.2 + EMA9 > EMA21 + RSI < 80

**Confidence scoring:**
- +0.25 breakout confirmed
- +0.10–0.20 rel_vol (>1.2 → +0.10, >1.5 → +0.20)
- +0.20 trend confirm (EMA9 > EMA21)
- +0.15 RSI in 50–75 range
- +0.10 positive 5-bar momentum
- +0.10 BB %B > 0.60

**Entry:** limit at `mid × (1 + 0.05%)`
**Stop:** `mid × (1 − 1.5%)`
**Target:** `mid × (1 + 2.5%)`

### 5b. Mean Reversion
**Signal:** RSI < 35 + BB %B < 0.15 (price at/below lower band) + NOT in strong downtrend (EMA9 not > 2% below EMA21)

**Confidence scoring:**
- +0.30 base (oversold + lower band)
- +0.10–0.20 RSI depth (<30 → +0.10, <25 → +0.20)
- +0.15 BB %B < 0.05
- +0.10 current bar is bullish (close > open)
- +0.10 EMAs converging (separation < 0.5%)

**Entry:** limit at `mid × (1 + 0.05%)`
**Stop:** `mid × (1 − 1.5%)`
**Target:** BB mid-band (minimum `mid × 1.01`)

### 5c. EMA Crossover
**Signal:** EMA9 freshly crosses above EMA21 (previous bar: EMA9 ≤ EMA21, current bar: EMA9 > EMA21) + RSI 40–72 + EMA separation > 0.05%

**Confidence scoring:**
- +0.30 base (fresh crossover)
- +0.15 RSI in healthy zone
- +0.15 price above SMA20
- +0.10 positive 5-bar momentum
- +0.08–0.15 EMA separation (>0.05% → +0.08, >0.15% → +0.15)
- +0.08 RSI in sweet spot 50–65

**Entry:** limit at `mid × (1 + 0.05%)`
**Stop:** `mid × (1 − 1.5%)`
**Target:** `mid × (1 + 2.5%)`

**Strategy priority:** momentum_breakout is checked first. mean_reversion only if no momentum signal. ema_crossover only if neither fired.

---

## 6. Fee Math (Critical — Coinbase Intro Tier)

```
Entry fee:      0.6% maker
Exit fee:       0.6% maker
Round-trip fee: 1.2%
Slippage est.:  0.05%
Take-profit:    2.5% (momentum/ema) or variable (mean_rev)
Net edge:       take_profit_pct × 100 − round_trip_fee_pct − spread_pct − slippage_pct
```

**For momentum/ema at 2.5% TP, 0.5% max spread:**
`Net edge = 2.5 − 1.2 − 0.5 − 0.05 = 0.75%` (if spread = 0.5%)

The risk manager rejects trades where `net_expected_edge_pct ≤ 0.0`.

---

## 7. Risk Manager Checks (in order)

1. Account health (not blocked/suspended)
2. Live trading gate (`LIVE_TRADING=true` env + `live_trading.enabled` config)
3. Equity floor (`equity ≥ $1.50`)
4. Asset class permitted for this account
5. Asset class permitted in live mode (per config)
6. Short-specific: requires `$2000+ equity` (always fails for this account)
7. Margin-specific: requires `$2000+ equity` (always fails for this account)
8. Options-specific: requires broker approval (Level 1 approved, long call/put only)
9. Crypto-specific: asset must be on allowed list + crypto_enabled flag
10. Daily loss limit (`≤ -$2.00`)
11. Consecutive losses (`< 2`)
12. Daily trade count (`< 5`)
13. API error rate (`< 10` per session)
14. No new trades after 14:45 local time
15. Max open positions (`< 4`)
16. Deduplication (no open order or position in same symbol)
17. Max notional (`≤ $2.00`)
18. Min notional (`≥ $0.50`)
19. Max total exposure check
20. Buying power check (`notional ≤ buying_power × 85%`)
21. **Fee hurdle** (`net_expected_edge_pct > 0.0`)
22. Order type supported (limit orders only for crypto)
23. Exit plan (stop-loss OR take-profit must be set)
24. Stale data (`quote age ≤ 120s`)
25. Spread check (`spread ≤ 0.5%`)
26. Confidence threshold (`≥ 0.65`)

---

## 8. Position Management

Each open position is checked every loop (~90 seconds):

- **Stop-loss:** close if current price ≤ stop level
- **Take-profit:** close if current price ≥ target
- **Max hold time:** force close after 90 minutes regardless of P/L
- **Force flat:** close all non-crypto positions before 14:55 local time
- **Abandoned positions:** if broker has a position with no session record, the bot adopts it with default stop/TP levels

**Net P&L calculation at exit:**
```
gross_pnl = (exit_price − entry_price) × qty
fees_paid = (entry_price × qty × 0.006) + (exit_price × qty × 0.006)
net_pnl = gross_pnl − fees_paid
```

Session daily P&L tracks net (after fees). Stop after daily loss of $2.00.

---

## 9. State Persistence

On startup, the bot loads `state/open_positions.json` and reconciles against live broker positions. Positions closed while the bot was offline are discarded. Positions still open at the broker are restored to session state with their original entry price, stop-loss, and take-profit.

---

## 10. Indicators Computed (market_data.py → add_indicators)

- EMA 9, EMA 21
- SMA 20
- RSI 14
- Bollinger Bands (20-bar, 2σ): upper, mid, lower, %B
- Volume SMA 10
- Relative volume (`vol / vol_sma_10`)
- 5-bar momentum (`close − close[5]`)

---

## 11. Known Weaknesses / Areas to Evaluate

The following are suspected problem areas — please evaluate and suggest concrete code improvements:

### A. Signal rarity / over-filtering
All three strategies require a relatively tight combination of conditions. In a sideways or low-volatility market (common for DOGE/ALGO), signals may never fire. Consider whether conditions are too strict or whether the confidence floor (0.65) is set too high relative to how confidence is scored.

### B. Fixed stop-loss and take-profit percentages
Stop (1.5%) and target (2.5%) are static across all symbols and market conditions. BTC/USD has very different volatility than ALGO/USD. ATR-based dynamic stop/target sizing would be more appropriate.

### C. Strategy priority is rigid
momentum_breakout blocks mean_reversion which blocks ema_crossover. If multiple valid signals exist simultaneously, only the first fires. Consider whether this is the right design.

### D. No short-side strategies
The bot is long-only. In a sustained downtrend, the bot simply waits (which is correct for a $10 account with these limits, but worth noting).

### E. 5-minute bars with 90-second loop
Scanning every 90 seconds on 5-minute bars means many loops produce no new bar data. The bot re-evaluates the same bar multiple times. Is there a smarter way to pace the strategy scan?

### F. Coinbase taker fees not modeled separately
The fee model assumes maker fills (0.6%). In practice, limit orders placed at `mid + 0.05%` may fill as taker if the market moves fast. Taker fee on Coinbase Intro is 1.2% — nearly double. This could flip a trade from profitable to unprofitable.

### G. No adaptive confidence scoring
Confidence scores are additive constants. There's no normalization or consideration of how conditions interact (e.g., very high relative volume might compensate for weaker EMA confirmation).

### H. Mean reversion TP is variable but not validated
Mean reversion targets BB mid-band but the actual % gain varies widely. Sometimes this is only 0.3%, which may not cover fees. The fee hurdle check helps, but BB mid-band is computed from historical bars and may lag.

### I. No regime detection
The bot doesn't know if the market is trending, ranging, or in high volatility. Momentum strategies underperform in ranging markets; mean reversion underperforms in trending markets. A simple regime classifier (e.g., ADX > 25 = trending) could route signal generation accordingly.

### J. DOGE and ALGO liquidity
These symbols have much wider spreads than BTC/ETH. The 0.5% spread check helps, but their price action is more manipulated and noisy. Worth considering whether they belong in the symbol list for a bot that relies on technical signals.

---

## 12. What We're Asking For

Please evaluate the strategies, risk logic, and overall design and suggest:

1. **Concrete code improvements** to strategy signal quality (conditions, confidence scoring, indicator choices)
2. **ATR-based or volatility-adjusted stop/target logic** to replace static 1.5%/2.5%
3. **Regime detection** — simple, fast, and compatible with the existing bar data pipeline
4. **Fee model improvements** — how to handle maker vs. taker uncertainty
5. **Any signal logic bugs** — cases where a condition is mis-coded or contradictory
6. **Confidence scoring improvements** — whether additive constants are the right approach
7. **Anything else** that would increase the probability of profitable trades without violating the hard rules in Section 2

Please be specific — pseudocode or actual Python edits are preferred over general advice.

---

## 13. File Map

```
alpaca-autonomous-microbot/
├── main.py                  — main loop, CLI args, startup checks
├── strategy_crypto.py       — all 3 crypto strategies
├── strategy_options.py      — options strategy (paper only, Level 1 approved)
├── strategy_shorts.py       — short strategy (disabled, needs $2000+)
├── risk_manager.py          — 26 checks, authoritative
├── position_manager.py      — exit logic, net P&L, state restore
├── order_manager.py         — order routing, session state updates
├── permissions.py           — broker account capability detection
├── market_data.py           — quotes, bars, indicator calculation
├── broker_alpaca.py         — Alpaca API wrapper
├── journal.py               — trade journal (CSV + structured logging)
├── utils.py                 — config, process lock, kill switch, persistence
├── config.yaml              — all tuneable parameters
├── .env.example             — API key template (never commit .env)
├── requirements.txt
└── tests/
    ├── test_risk_manager.py   — 30+ deterministic risk layer tests
    ├── test_permissions.py    — broker capability detection tests
    └── test_config.py         — config defaults and kill switch tests
```

---

*All 73 unit tests pass as of 2026-05-24. Bot is running live on Alpaca/Coinbase with a ~$10 account.*
