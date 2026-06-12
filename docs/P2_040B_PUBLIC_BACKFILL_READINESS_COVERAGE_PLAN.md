# P2-040B Public Backfill Readiness / Coverage Plan Generator

## Purpose

Provides a dry-run-only coverage planning tool that computes the exact public OHLCV backfill requests needed to reach replay-grade coverage, without actually performing any network fetches.

## Why This Comes After P2-040A

P2-040A implemented the strict approval runner that wraps the P2-039D adapter, requiring an explicit flag and approval token to fetch real data.
P2-040B uses that strict interface to generate *informational* commands. It scans existing local data (from P2-039C), calculates the missing gaps (bars), and produces a machine-readable plan detailing the exact arguments and commands required to fill those gaps via P2-040A.

## Plan-Only / No-Fetch Behavior

- The script NEVER fetches data.
- The script NEVER writes market data to the filesystem.
- It only reads existing JSON manifests (if present) and calculates expected bars.

## Coverage Planning Fields

The generator calculates and outputs:
- Expected bars based on requested timeframe and start/end dates.
- Existing coverage by scanning local Parquet manifests.
- Missing bars (expected - existing).
- Estimated coverage percentage.
- The required informational commands to fill the gaps, broken into chunks if requested.

## Future Approval Command Generation

The script outputs `future_commands`. These commands invoke `p2_040a_public_backfill_approval_runner.py` with the required explicit safety flags:
- `--allow-public-fetch`
- `--approval-token PUBLIC_BACKFILL_APPROVED`

These commands are informational. They MUST NOT be run without separate, explicit user approval.

## Strict Limits

- **NO** authenticated broker APIs are used.
- **NO** account endpoints are accessed.
- **NO** orders are submitted, cancelled, or closed.
- **NO** generated data artifacts (Parquet, DuckDB) are committed.

## Machine Learning Blocked

ML, prediction, and online learning remain blocked until replay-grade historical coverage exists. The current economic baseline remains unprofitable:

`NET_PNL≈-$1.58 across 80 historical trades`
