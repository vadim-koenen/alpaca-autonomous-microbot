# Open-Source Bot Plumbing Survey

## Purpose

P2-009 documents reusable architecture patterns from mature public trading-bot projects.

This is a Class 1 read-only planning patch. It does not copy external code, install packages, change live execution, change config, touch secrets, restart bots, or alter strategy behavior.

The goal is to use proven public-bot plumbing ideas to accelerate our path to reliable measurement, realized P/L, safer execution, and eventually profit-focused tuning.

## Why this exists

P2-007 proved local Coinbase journals contain exit rows but no direct sell proceeds and no fee rows.

P2-008 defined the immutable Coinbase fill log contract and added a checker. The checker currently reports that `logs/coinbase_fills.csv` is missing.

Therefore, the next useful work is not strategy tuning. The next useful work is learning from mature bot plumbing and mapping those concepts to this repo before implementing live fill logging.

## Safety classification

Class 1: advisory / documentation / reference survey only.

This patch must not:

- call broker APIs
- read `.env`
- place, cancel, or modify orders
- restart bots
- run `launchctl`
- change config files
- change risk caps
- touch `state/`, `runtime/`, or `launchd/`
- touch broker, order manager, risk manager, main loop, or strategy execution files
- connect predictions to live trading

## Reference projects

### Freqtrade

Primary use for our project: order lifecycle, trade persistence, fee-aware accounting, and fill callbacks.

Relevant pattern to adopt conceptually:

- explicit order-filled callback after actual execution
- persistent trade/order object model
- fee-aware trade accounting
- separation of trade intent from exchange fill reality

License caution: Freqtrade is GPL-licensed. Do not copy code into this repo unless license implications are explicitly accepted. Use it as architecture reference only.

### Hummingbot

Primary use for our project: exchange connector isolation and event-driven order lifecycle.

Relevant pattern to adopt conceptually:

- connector owns exchange-specific behavior
- order lifecycle emits events
- strategy consumes standardized order/fill events
- fee details are part of trade-event correctness

License note: Hummingbot is Apache 2.0, but this patch still does not copy code. It only records architecture lessons.

### Jesse

Primary use for our project: research to backtest to live workflow discipline.

Relevant pattern to adopt conceptually:

- same strategy lifecycle should be testable before live deployment
- backtesting and optimization must not diverge from live execution semantics
- logs, metrics, and monitoring are part of live-readiness

### OctoBot / CCXT

Primary use for our project: secondary reference for exchange abstraction, paper trading, and backtesting support.

Relevant pattern to adopt conceptually:

- exchange abstraction reduces broker-specific sprawl
- paper/backtest modes should be first-class, not afterthoughts
- CCXT-style exchange integration is useful for conceptual comparison, even if Coinbase Advanced direct integration remains custom

## Plumbing patterns to integrate into this bot

### 1. Fill event is the source of truth

The bot must distinguish order intent from order fill.

An intended exit is not realized P/L. A realized exit requires exchange fill data, proceeds, and fee information.

### 2. Immutable fill ledger

Coinbase fills should be written as append-only rows to `logs/coinbase_fills.csv` using the P2-008 contract.

No normal bot operation should rewrite previous fill rows.

### 3. Stable cycle ID

Every entry and exit pair needs a stable local lifecycle ID such as `cycle_id`.

Without a stable cycle ID, pairing buy and sell fills degrades into weak timestamp matching.

### 4. Exchange connector boundary

Coinbase-specific API details should be isolated behind a narrow boundary.

Strategy code should not need to know Coinbase response shapes.

### 5. Fee-aware realized P/L

Gross P/L is not enough.

Net P/L requires actual fees from the exchange or a clearly marked fee-estimation mode.

### 6. Paper/backtest/live parity

Reports and checkers should read from a common event/fill schema where possible.

This reduces the risk of optimizing in reports but failing in live execution.

### 7. Reconciliation before tuning

Before changing TP/SL, hold time, notional, symbol selection, or prediction-to-live behavior, the bot must be able to reconstruct realized P/L from actual fill data.

## Mapping to current repo gaps

Current confirmed gap:

- `logs/coinbase_fills.csv` is missing
- current Coinbase journal contains exits but lacks direct sell proceeds
- fee rows are missing
- realized gross/net P/L remains unsafe

Required next discovery:

- find where Coinbase orders are submitted
- find where Coinbase responses are normalized
- find where fill status is available
- find whether sell proceeds and fees are available from current responses
- find the safest append-only hook for fill logging
- confirm no implementation requires order behavior changes

## Recommended next patches

### P2-010 — Coinbase Fill Logging Implementation Discovery

Class 1, read-only. Search this repo for Coinbase order submission, response parsing, journal writing, and available fill/proceeds/fee fields.

Output should be a map of files/functions and a recommended implementation seam.

### P2-011 — Coinbase Immutable Fill Logging Implementation

Potentially higher risk because it may touch execution-path files.

Must be tightly scoped to append-only logging. No strategy behavior changes. No order sizing changes. No exit changes. No config risk-cap changes.

### P2-012 — Realized P/L Reconciliation from Fill Ledger

Run P2-007/P2-008 style checks against actual `logs/coinbase_fills.csv` data once available.

Only after P2-012 produces reliable realized P/L should Class 2 tuning be reconsidered.

## Do not do yet

- Do not install or migrate to Freqtrade, Hummingbot, Jesse, OctoBot, or CCXT.
- Do not copy GPL code.
- Do not copy public strategy logic.
- Do not change live bot behavior.
- Do not tune notional, TP/SL, hold time, or prediction-to-live behavior.

## Bottom line

Use public bot frameworks as plumbing references, not as strategy sources.

The immediate path to profit remains measurement truth: actual fills, actual proceeds, actual fees, stable cycle IDs, and reliable realized P/L.
