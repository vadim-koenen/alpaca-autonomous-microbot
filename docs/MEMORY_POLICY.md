# Memory Policy

This bot uses memory to improve operational reliability, not to self-expand risk.

## Memory Layers

Working memory is in-process state for the current loop: permissions, account state, proposals, session counters, and open positions.

Semantic memory is durable factual context: broker capabilities, risk caps, account constraints, and approved operating rules.

Procedural memory is durable operating practice: how to reconcile, how to check auth safely, how to restart launchd, and how to validate changes.

Distillation memory is the daily summary layer produced from events, journals, state files, and heartbeats.

## Never Learn Automatically

The bot must never automatically learn or deploy higher sizing, new symbols, options, margin, short selling, leverage, live strategy changes, or risk-cap changes. Those require human approval and a reviewed config patch.

Secrets must never be written to memory. API keys, private keys, bearer tokens, passwords, and credential values are redacted before config hashing or memory storage.

## Improvement Loop

observe -> record -> summarize -> distill -> recommend -> paper-test -> human approval -> deploy

Recommendations are advisory. The risk manager remains authoritative.

## Storage

Runtime recovery stays in broker-specific JSON files under `state/`.

The durable audit layer is SQLite at `memory/bot_memory.sqlite3`.

Daily distillations are written under `memory/distillations/`.
