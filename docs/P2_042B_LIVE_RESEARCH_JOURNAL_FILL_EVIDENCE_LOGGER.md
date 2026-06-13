# P2-042B Live Research Journal / Fill Evidence Logger

## Purpose

P2-042B adds isolated evidence-capture scaffolding for future bounded live
research. It does not enable `LIVE_RESEARCH_FOR_DATA`, approve
`LIVE_TRADING_FOR_PROFIT`, connect to a broker, place an order, or change live
strategy, risk, sizing, capital, or runtime behavior.

The goal is to make every future research trade scientifically useful rather
than merely producing a profit/loss number.

## Evidence Schema

`live_research_journal.py` defines a fixed flat schema and these event types:

- `research_session_started`
- `proposal_evaluated`
- `trade_intent_created`
- `order_submitted_observed`
- `fill_observed`
- `position_mark_observed`
- `exit_observed`
- `skip_observed`
- `kill_switch_triggered`
- `research_session_closed`

Every event carries stable session, run, correlation, symbol, mode, strategy,
signal, decision, source, policy-linkage, and live-versus-replay fields.
Event-specific validation requires the relevant proposal, quote, order, fill,
fee, slippage, MFE/MAE, exit, skip, and replay-divergence evidence.

## Fail-Closed Validation

Invalid events return explicit missing or invalid field reasons. Append refuses
an event before creating or changing a journal file when validation fails.

Future live research must fail closed when any of these are missing:

- Journal capture
- Fill evidence
- Fee amount, fee currency, or fee basis points
- Position-mark MFE/MAE evidence

The readiness helpers are pure and intended for later use by P2-042A/P2-042C.
They do not authorize execution.

## Measurements

The module supports:

- Spread basis points from bid, ask, and optional mid
- Signed adverse slippage basis points for buys and sells
- Long and short MFE/MAE updates from entry and mark prices
- Fill completeness and fee completeness checks
- Structured skip and exit reasons
- Replay dataset, replay window, expected decision, live decision, and
  divergence linkage

Future research must record fills, fees, slippage, spread, MFE/MAE, skip
reasons, exit reasons, and live-versus-replay divergence.

## Privacy

Secret-like and credential-like keys or values are rejected. Account,
portfolio, and wallet identifier fields are rejected. Raw environment values
are not part of the schema. Events must be JSON serializable and flat.

## JSONL Output

Append requires an explicit `.jsonl` path. There is no default runtime path.
Serialization is deterministic and writes exactly one JSON object per line.
Tests write only under pytest `tmp_path`.

Runtime research journals are generated artifacts. They must remain uncommitted.

## Non-Approvals

This patch does not:

- Enable live research
- Approve live trading for profit
- Enable ML live influence or online learning
- Call authenticated broker APIs
- Mutate broker or order state
- Change strategy, risk, sizing, capital, notional, or asset scope
- Restart live services or touch runtime kill switches

## Next Patch

The recommended next patch is **P2-042C Research Budget Monitor + Auto-Kill**.
