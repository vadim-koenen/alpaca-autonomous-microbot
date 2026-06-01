# BROKER PAYLOAD REDACTION POLICY

**Purpose**: Define the minimum redaction standards for any broker payload (fills, orders, account data, etc.) that is captured, logged, or displayed in reconciliation or diagnostic tools.

**Scope**: Applies to all scripts, tests, fixtures, and documentation in this repository that handle Coinbase (or any broker) responses.

---

## Fields That Must Be Redacted

- account_id, account_uuid, portfolio_id, user_id
- Any API key, secret, token, or bearer value
- client_order_id (when it could be used to correlate with external systems)
- Raw wallet addresses or deposit addresses
- Authorization headers or full URLs containing credentials
- Any field whose name contains "secret", "key", "token", "auth", "password", or "credential"

---

## Recommended Redaction Methods

1. **For long identifiers** (order_id, trade_id, client_order_id when redaction is required):
   - Show only the last 4–6 characters: `...a1b2c3`

2. **For nested objects**:
   - Recursively redact any key matching the sensitive list.
   - Replace the value with the string `"<REDACTED>"`.

3. **For display in logs or reports**:
   - Never print raw sensitive values even in debug mode.
   - Use a helper such as `redact_broker_payload.py` (if present) before any output or storage.

---

## Implementation Guidance

- Any script that captures live broker data (even in controlled read-only mode) must apply redaction before writing to stdout, files, or logs.
- Fixtures used in tests may contain synthetic or already-redacted data. Never commit real sensitive values.
- When adding new reconciliation or capture scripts, include redaction as a non-optional step in the output path.

---

**End of policy.** Update this document when new sensitive field patterns are discovered or when redaction helper behavior changes.