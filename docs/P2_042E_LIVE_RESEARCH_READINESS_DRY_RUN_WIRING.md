# P2-042E: Live Research Readiness / Dry-Run Wiring

## Overview
This patch provides the foundational wiring between the previously isolated components:
- P2-042A: Policy Gate
- P2-042B: Evidence Journal
- P2-042C: Budget Monitor
- P2-042D: Exploration Queue

It ties them together into a non-executable dry-run report layer. 

**Important:** This patch explicitly does *not* enable live trading. It only answers the hypothetical question: "Would a research session be ready for an approval packet, if an approval packet were to be evaluated?"

## Status Pipeline
The readiness process checks each component sequentially and fails closed. The possible outcomes are:
1. `READY_FOR_APPROVAL_PACKET`: All required components have cleared, meaning the system is waiting purely on explicit human token/phrase approval to execute.
2. `BLOCKED_POLICY`: `live_trading_for_profit` is set to True (which is illegal in this branch structure).
3. `BLOCKED_EVIDENCE_CAPTURE`: The required journal paths or loggers are unavailable or invalid.
4. `BLOCKED_BUDGET`: The budget monitor returns `KILL` or `FAIL_CLOSED`.
5. `BLOCKED_NO_CANDIDATE`: The exploration queue is empty or no valid high-edge proposals were generated.
6. `BLOCKED_MISSING_APPROVAL`: Used internally when simulating full validation; if the approval token is absent.
7. `BLOCKED_RUNTIME_MUTATION`: A check failed involving state mutation that was incorrectly triggered.

## Implementation Invariants
- `executable` is strictly `False`.
- `order_submission_enabled` is strictly `False`.
- `broker_api_required` is strictly `False`.
- `runtime_mutation_required` is strictly `False`.

## Next Steps
The next patch should be `P2-042F Research Session Launch Preflight / Approval Packet`.
