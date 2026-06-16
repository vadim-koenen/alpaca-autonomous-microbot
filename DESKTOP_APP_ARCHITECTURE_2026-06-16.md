# Desktop App Architecture — Accumulator/Allocator control surface (2026-06-16)

Author: Claude (senior eng). Audience: operator + GPT. Captures the **desktop-app scope** (raised
by the operator; dropped from the long GPT chat) so it is not lost again, and sets the architecture
so every backend deliverable is already app-ready.

## What the app IS (and is NOT)

**IS:** a local, human-in-the-loop **control surface + dashboard** for the accumulator/allocator. It
shows portfolio state, the plan for the period, drawdown/contributions, and (later) news/risk alerts.
The operator reviews and approves; the app never trades autonomously.

**IS NOT:** an autonomous trader, a signal/prediction tool, or anything that places orders without an
explicit human action. All governance holds: live stays NO-GO until offline gate → paper → bounded
live; `runtime/STOP_TRADING` still arms the kill-switch; the app surfaces a plan, it does not fire it.

## Why this fits the project

The pivot makes the bot a *disciplined accumulator*, and discipline is exactly what a dashboard
enforces: it keeps the human in the loop, makes the (boring, correct) plan visible, and is the natural
home for the **news advisory + risk-alert** module (the only honest role left for news). The app is the
UI over logic that already exists — it adds **zero** new trading authority.

## Stack recommendation (all-Python codebase → lowest friction)

| Layer | Choice | Why |
|---|---|---|
| **Decision logic** | existing `allocator_engine.py`, `accumulator_allocator.py` | already pure, tested, broker-agnostic |
| **Backend API** | **pywebview `js_api`** (v1) — Python methods called directly from the UI | single-user local app needs no server; fewer deps. FastAPI optional later for multi-client |
| **Frontend** | single-page web UI (plain HTML/JS or lightweight framework) | simple, portable, easy to render orders/charts |
| **Desktop shell** | **pywebview** for v1 (native window over the local UI) | Python-native, tiny, no Node toolchain; **Tauri** later if a signed installer is wanted |
| **State** | local JSON/SQLite (portfolio, contributions, plan history) | offline, inspectable, backup-friendly |
| **Broker** | Alpaca (paper first), behind an executor that checks `STOP_TRADING` + human approval | governance preserved |

This is a *recommendation, not a lock* — the one decision to confirm before scaffolding the UI is
pywebview-vs-Tauri-vs-PyQt. Everything below is stack-agnostic until then, so backend work proceeds now.

## Component / data flow

```
 Alpaca market data (read-only) ─┐
                                 ▼
   prices ──► allocator_engine.plan_period(portfolio, prices, weights, contribution)
                                 │            (P2-046B, built)
                                 ▼
                          List[Order]  ──►  FastAPI  ──►  Web UI (review)
                                 │                              │ operator clicks "Approve (paper)"
                                 ▼                              ▼
                     local state (JSON/SQLite)         executor (paper→live, STOP_TRADING-gated)
                                 ▲                              │
       news/risk module (advisory + alerts) ──────────────────┘  (P2-046C; never an entry signal)
```

## Screens (v1)

1. **Portfolio** — holdings, current vs target weights (drift bars), total value, max drawdown, contributions to date.
2. **This period's plan** — the `List[Order]` from `plan_period` with reasons (dca / rebalance_buy / rebalance_sell); an **Approve (paper)** button (disabled while `STOP_TRADING` armed / before M4).
3. **History** — past contributions, plans, and (paper) fills; equity curve.
4. **Alerts** — news/risk circuit-breaker notices (P2-046C); informational, with a manual "pause auto-contributions" toggle.
5. **Settings** — basket, target weights, contribution amount/cadence, rebalance band, cost assumptions.

## Phased build (offline-first; nothing live without approval)

- **P2-046A** ✅ basket backtest (DCA vs overlay) — verdict: plain DCA, overlay off.
- **P2-046B** ✅ allocator engine (`plan_period`, contribution-funded rebalance, `apply_orders`).
- **P2-046C** — news module as a separate non-trading advisory/risk service (reuse `fetch_alpaca_news.py`).
- **P2-046D** — portfolio state store + paper executor (Alpaca paper, `STOP_TRADING`-gated, human-approve).
- **P2-046E** — FastAPI backend exposing engine + state as JSON.
- **P2-046F** — web UI + pywebview desktop shell (the 5 screens).
- **M4 paper repro → M5 bounded live** — only after offline + paper pass; caps unchanged.

## Governance line (unchanged)

No live trading, no restart, no order mutation, no autonomous execution. Alpaca keys in `.env`, never
printed/committed. The app proposes; the human disposes; paper precedes live; `STOP_TRADING` always wins.
