# P2-042A Live Research Mode Policy + Config Gate

## Purpose

P2-042A defines an isolated, fail-closed policy scaffold for a future bounded
`LIVE_RESEARCH_FOR_DATA` mode. It does not connect the policy to `main.py`,
strategy selection, risk approval, sizing, broker clients, or order placement.
Both live research and live profit trading remain disabled by default.

## Mode Separation

`LIVE_RESEARCH_FOR_DATA` means paid evidence collection. A future approved
window may intentionally spend a fixed loss budget to measure real fills, fees,
slippage, adverse selection, MFE/MAE, skip behavior, and live-versus-replay
differences. Losses are expected and treated as bounded research tuition.

`LIVE_TRADING_FOR_PROFIT` is a separate mode that requires proven edge. It
remains false and is not approved by this patch. Live research does not prove
profitability and must never imply that profit trading is approved.

## Defaults

The standalone `config_live_research.yaml` is not loaded by the runtime. Its
defaults are:

- `LIVE_RESEARCH_FOR_DATA=false`
- `LIVE_TRADING_FOR_PROFIT=false`
- `LIVE_RESEARCH_APPROVAL_REQUIRED=true`
- Empty approval text, loss budgets, limits, symbols, and expiry
- All research kill switches enabled
- ML live influence disabled
- Online learning disabled

## Future Approval Gate

A future research window must include this exact phrase with a positive budget:

`LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence collection with max loss budget $<amount>`

The amount in the phrase must exactly match `LIVE_RESEARCH_BUDGET_USD`. A
research window also requires positive daily and weekly loss caps, positive max
single-trade notional, positive max research trades per day, at least one
allowed symbol, and a timezone-aware future expiry timestamp.

## Fail-Closed Conditions

The pure policy gate blocks a future research window when any required config
is absent or invalid. It also blocks on:

- Total research budget exhaustion or breach
- Daily or weekly research loss-cap exhaustion or breach
- Expired or invalid research-mode expiry
- Broker error
- Missing journal capture
- Missing fee capture
- Missing fill capture
- Missing MFE/MAE capture
- Any attempt to disable a required research kill switch
- Any attempt to enable profit trading, ML live influence, or online learning

## Explicit Non-Approvals

P2-042A does not:

- Enable live trading or place orders
- Approve `LIVE_TRADING_FOR_PROFIT`
- Prove profitability
- Increase capital or notional
- Change strategy behavior, risk caps, or sizing
- Approve ML live influence or online learning
- Call authenticated broker APIs
- Restart live services or alter runtime state

## Required Follow-Up

Future patches must add and validate journal, fill, fee, and MFE/MAE evidence
capture before any live research approval can be used safely. The recommended
next patch is **P2-042B Live Research Journal / Fill Evidence Logger**.
