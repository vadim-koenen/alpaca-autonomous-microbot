# Manual-Review Position Blocker Diagnostics

P2-029A adds an offline, read-only operator diagnostic for Coinbase entry
blocking caused by local manual-review position state. It diagnoses state; it
does not clear, normalize, close, or otherwise remediate positions.

## Inputs

The tool reads only the paths supplied on the command line, or these local
defaults:

- `journal_coinbase_crypto.csv`
- `state/coinbase/open_positions.json`
- `state/coinbase/external_inventory.json`
- `state/coinbase/closed_positions.json`

Process count is not inspected automatically. An operator may provide previously
captured process-list text with `--ps-text`; otherwise it is reported as
`not evaluated`.

## Output

The report identifies:

- active manual-review blockers in open-position and external-inventory state;
- the latest ADA entry/fill, failed-close warning, and broker-reassociation
  warning available in the journal;
- recent `ENTRY_BLOCKED reason=manual_review_position_open` rows;
- duplicate live-process risk when captured process text contains more than one
  `main.py --mode live` process;
- the manual confirmations required before a separate remediation proposal.

Default behavior prints only. `--output PATH` is the sole write option and
writes only the requested report path.

## Fixture Smoke

```bash
python3 scripts/coinbase_manual_review_blocker_diagnostics.py \
  --journal tests/fixtures/coinbase_manual_review_blocker_diagnostics/journal_coinbase_crypto.csv \
  --open-positions tests/fixtures/coinbase_manual_review_blocker_diagnostics/open_positions.json \
  --external-inventory tests/fixtures/coinbase_manual_review_blocker_diagnostics/external_inventory.json \
  --closed-positions tests/fixtures/coinbase_manual_review_blocker_diagnostics/closed_positions.json \
  --ps-text tests/fixtures/coinbase_manual_review_blocker_diagnostics/ps.txt \
  --json
```

## Safety Boundary

The diagnostic does not access broker endpoints, authentication material,
network services, process controls, or order methods. It does not inspect
`.env`, change live configuration or risk, mutate state, clear manual-review
flags, or unblock trading.

All authorization flags remain false. An operator must manually confirm
Coinbase balances for ADA, SOL, BTC, and ETH. No blocker should be cleared while
duplicate live-process risk exists. Any remediation requires a separate review
and explicit approval.
