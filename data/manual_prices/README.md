# Manual Price Import

Manual price files are advisory-only inputs for shadow outcome labeling. They
must not contain account IDs, API keys, tokens, or private identifiers.

JSONL row format:

```json
{"source":"manual","symbol":"BTC/USD","asset_class":"crypto","timestamp_utc":"2026-05-28T12:16:45Z","open":73262.21,"high":73280.0,"low":73200.0,"close":73262.21,"volume":1.0,"timeframe":"1m"}
```

Import and label:

```bash
python3 scripts/shadow_import_prices.py --input-file data/manual_prices/sample_prices.jsonl --dry-run
python3 scripts/shadow_import_prices.py --input-file data/manual_prices/sample_prices.jsonl
python3 scripts/shadow_label_outcomes.py --since 2026-05-28
python3 scripts/shadow_learner_report.py --since 2026-05-28
```

Equity fixture:

```bash
python3 scripts/shadow_import_prices.py --input-file data/manual_prices/equity_sample_prices.jsonl --dry-run
python3 scripts/shadow_import_prices.py --input-file data/manual_prices/equity_sample_prices.jsonl
```

`equity_sample_prices.jsonl` is a format fixture for the equity symbols already
seen in shadow snapshots (`SPY`, `QQQ`, `AAPL`, `MSFT`, `NVDA`). Its timestamps
are intentionally old sample timestamps and must be replaced with verified
historical intraday equity prices before using it to label 2026 outcomes.
