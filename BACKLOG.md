# BACKLOG — standing "what's next" so the project never stalls on ideas

The accumulator is a **finished utility**. This is the closed list of what's genuinely worth doing,
so progress never depends on inventing new ideas. Pick from here.

---

## The honest money-generation landscape (read this first)

"Make money with a background bot" has exactly three buckets. Two are real; one is dead.

| Bucket | What it is | Real for retail? | Status here |
|---|---|---|---|
| **Beta** — own the market | Hold a diversified basket; capture market return + dividends + T-bill interest | ✅ Yes, automatic | **DONE** — the accumulator already does this |
| **Carry / yield** — get paid to bear a risk or provide a service | Funding-rate arb, options premium, staking | ⚠️ Real but modest + risky | **1 untested lane** (see below) |
| **Alpha** — predict direction better than the crowd | Technical/news/ML trading signals | ❌ No (proven 3× here) | **DEAD** — do not revisit |

**The binding constraint is capital + time, not cleverness.** A 10% edge on $500 is $50/year. There is no
clever-bot shortcut to wealth — there is owning assets (beta) and occasionally harvesting structural
premia (carry), both of which scale with money and patience. Internalize this and the rest is easy.

---

## The ONE remaining edge-like experiment: carry strategies

If you want a background bot that aims *beyond* market beta, this is the only honest candidate left:

- **Crypto funding-rate arbitrage (market-neutral):** hold spot long + perpetual-future short in equal
  size → delta-neutral; collect the funding rate perps pay. You're paid for *providing leverage*, a
  structural service — no direction forecast (the skill we proved you don't have). Historically real,
  low-double-digit % annualized in good regimes.
- **Honest caveats:** real risks — exchange/counterparty, liquidation on the short leg, funding flipping
  negative, two-leg execution slippage. Returns are modest and capacity-limited. Needs a venue with both
  spot + perps.
- **Discipline (non-negotiable, same as before):** OFFLINE backtest net of ALL costs → paper → bounded
  live. "No edge / stop" stays a valid result. Do NOT go live on a hope.

This is the next *experiment* if you want one. It is not a sure thing; it is the only lane not yet falsified.

---

## Operational — just use what's built (highest value, no code)
1. Run on paper a few weeks; feel a small drawdown to calibrate risk tolerance.
2. Go live with the $10 (`--enable-live`), then enable auto-invest (`--enable-auto`).
3. Set up **Alpaca's own recurring deposit** (bank → Alpaca); the bot deploys it. (Bot never touches your bank.)

## Commercial — only if you want a business (gated on YOU, not code)
4. Apple Developer cert ($99/yr) → code-signing/notarization scripted into `setup_app.py`.
5. Validate demand (landing page, 20 user conversations) BEFORE any mobile build.
6. Securities lawyer before touching anyone else's money (RIA/BD reality).

## Optional polish (truly optional — short list)
7. Transactions/history view in the dashboard.
8. Performance-vs-benchmark line (you vs. buy-and-hold SPY).
9. Tax-lot / cost-basis tracking for real-money reporting.

---

## What NOT to do
- Don't "optimize the algorithm" — that was the dead end. Over-tinkering hurts returns.
- Don't add directional/news/ML trading signals — falsified here (P2-044H, P2-045).
- Don't let a bot pull from your bank — Alpaca's recurring deposit owns that leg.
