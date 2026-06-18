# Course-Correction Summary — for GPT (PM review) — 2026-06-17

Author: Claude (senior eng, local terminal). Audience: GPT (PM) + collaborators.
You were PM during the edge-hunt and were last synced *before* the pivot. This is the high-level
"what changed and why" so you can review and give feedback without reading 15 status blocks in
`docs/ACTIVE_HANDOFF.md` (full detail is there; branch is on GitHub, 240 tests passing).

## TL;DR

The trading-bot thesis is **dead and proven dead** (3 lanes falsified on real data). We pivoted the
product from **"a bot that predicts/picks trades"** to **"a disciplined, automated accumulator/allocator"**
— a personal investing app (paper now, live-ready), with a path to commercialization. Real money is
still OFF. I want your read on the pivot direction and the open questions at the bottom.

## Why we pivoted (the falsification)

| Lane | Test | Verdict |
|---|---|---|
| Price-technical (crypto) | `analyze_live_journal.py`, 54 real trades | NO_EDGE — gross ≈ 0 *before* fees |
| News / sentiment | `news_edge_research.py`, 110k headlines | NO_NEWS_EDGE — "signal" was a momentum proxy + a counting artifact |
| Equities-swing | `run_pivot_gate.py`, real SPY/QQQ | NO_GO — positive EV but loses to buy-and-hold, 0% OOS robustness |

Root cause: all three are the same bet — **retail directional prediction on liquid public markets**,
which has no edge. Conclusion baked into `FRAMEWORK_EDGE_DISCOVERY_2026-06-16.md`: stop hunting alpha;
the only honest money is **beta** (own the market) + **carry** (one untested lane) — not prediction.

## What got built since you were last in the loop (P2-046 series)

A complete personal-investing app, all paper, all tested:
- **Accumulator engine** — DCA into a fixed, human-chosen basket; contribution-funded rebalancing
  (steers new money to underweights, never sells winners). No asset-picking, ever.
- **Capital-adaptive allocation** — target weights glide with total balance (Seed→Build→Grow), across
  **3 selectable risk presets** (Preservation / Income / Growth).
- **Income/index funds + auto-reinvest (DRIP)** — SGOV, SCHD, VTI, BND, GLD, BTC; dividends+interest
  redeploy automatically.
- **Desktop app** (pywebview, dock app) with a **stupid-simple dashboard** (color-driven up/down, "what's
  moving it"), live Alpaca prices, **macOS-Keychain key entry**, notifications.
- **Proactive daily check-ins** — "today's suggested action" (contribute / reinvest / rebalance / pause
  on risk) so the operator is nudged instead of having to think of next steps.
- **Honest research assistant** — ticker → real (split-adjusted) data: return, vol, drawdown, correlation
  to the basket, portfolio-fit. HARD RULE: never predicts, never says buy/sell.
- **Gated execution ladder** — simulate → paper (fake money, own keys) → live (real money, multi-gated:
  explicit enable + confirm + $ cap + kill-switch). Level-3 full-auto exists, off by default, auto-pauses
  on a news risk alert.

## Honesty guardrails held throughout (please pressure-test these)
- No directional prediction anywhere. The research assistant educates/diagnoses; it does not forecast.
- News is advisory/risk-only (circuit-breaker), never an entry signal.
- The bot does NOT pull from the bank — Alpaca's own recurring deposit owns that leg.
- Commercialization is gated on real-world items (Apple cert, securities lawyer, demand validation),
  NOT code. "Sell the algorithm" is off the table because there is no algorithm edge.

## Operator decisions made (for your review)
1. Pivot trader → accumulator: **accepted**.
2. Risk profile: **Income** preset (short horizon, preservation+income, untested risk tolerance).
3. Start on **paper**, then real **$10**, with Alpaca recurring-deposit funding.
4. Add income/index funds + auto-reinvest: **done**.
5. "Researcher" = the **honest** educational version, not a winner-predictor: **agreed**.

## OPEN QUESTIONS — where I want PM feedback
1. **Is the pivot the right call**, or do you see a lane we wrote off too quickly? (My view: the 3
   falsifications are solid; alpha is dead for this operator.)
2. **Commercial path:** is a non-custodial "simple automated investing" app a viable product given the
   crowded, regulated market — or is the honest answer "great personal tool, not a business"?
3. **The one beyond-beta experiment:** worth building the offline crypto funding-rate **carry** backtest
   (the only un-falsified edge-like lane), or leave it and let the accumulator be the product?
4. **Go-live readiness:** ~1 week of paper to watch the automation fire, then $10 live. Agree, or want a
   firmer paper gate first?

## State
Branch `review/p2-045-news-edge-research` (pushed, in sync). 240 tests pass. Real money OFF;
`runtime/STOP_TRADING` present; PAPER mode. `BACKLOG.md` = the finite remaining roadmap.
