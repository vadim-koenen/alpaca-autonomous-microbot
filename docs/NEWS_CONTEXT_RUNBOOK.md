# News Context Runbook

The news context layer is advisory-only. It writes structured market narrative
records to shadow learner tables and is not used for live orders, risk
approval, sizing, symbol selection, or strategy decisions.

## Manual Import

Use JSONL for screenshot or briefing snippets:

```bash
python3 scripts/shadow_news_ingest.py --input-file data/manual_news/2026-05-28_coinbase_market_briefing.jsonl --dry-run
python3 scripts/shadow_news_ingest.py --input-file data/manual_news/2026-05-28_coinbase_market_briefing.jsonl
python3 scripts/shadow_news_report.py --since 2026-05-28
```

Each line should include:

- `source`
- `title`
- `summary`
- `published_at_utc`
- `source_url`, blank if unknown
- `source_note`, for example `Manually imported from user-provided screenshot.`

## Safety

- Do not paste API keys, tokens, account IDs, or private identifiers.
- The ingest script redacts obvious secret-like values before storing/displaying
  text, but source snippets should still be treated as operator-visible data.
- Do not use this layer to change live trading limits or behavior.
