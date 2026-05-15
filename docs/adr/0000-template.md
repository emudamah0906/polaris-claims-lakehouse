# ADR-NNNN: <Decision Title>

**Status:** Proposed | Accepted | Superseded by ADR-XXXX
**Date:** YYYY-MM-DD
**Decision-makers:** <names / roles>

## Context

What is the situation that requires a decision? What forces are in play — technical, business, regulatory, organizational? What constraints apply (budget, deadline, team skill, existing systems)?

State the problem precisely. An ADR that doesn't pin down the *real* constraints reads as opinion, not engineering.

## Decision

The decision in one sentence, then the detail. Be specific: name versions, configuration modes, library choices.

## Alternatives considered

For each alternative seriously evaluated:

### Alternative A: <name>
- **Pros:**
- **Cons:**
- **Rejected because:** <the specific blocker — not just "less good">

### Alternative B: <name>
- **Pros:**
- **Cons:**
- **Rejected because:**

If you only list one alternative, you are doing it wrong. Also include any options that were briefly considered and dismissed — note why they didn't merit deeper analysis.

## Consequences

### Positive
- Concrete benefits this decision unlocks.

### Negative / accepted trade-offs
- The cost we are explicitly accepting. If this section is empty, you have not been honest.

### Mitigations
- How we reduce the impact of the negatives. Reference runbooks, alerts, or follow-up work.

## Revisit triggers

What would cause us to reopen this decision? E.g., "if Kafka throughput exceeds 100k msg/sec sustained" or "if regulatory mandate requires single-cloud Azure footprint." A good revisit list keeps future engineers from re-litigating from scratch.
