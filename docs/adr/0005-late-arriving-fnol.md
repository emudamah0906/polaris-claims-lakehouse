# ADR-0005: Late-arriving FNOL handling — bounded streaming watermark + batch reprocess

**Status:** Accepted
**Date:** 2026-05-14
**Decision-makers:** Polaris architecture

## Context

Insurance claims are uniquely bad at event-time discipline. The loss event happened on day T (e.g. a car accident, a storm). The First-Notice-of-Loss (FNOL) is filed when the policyholder gets around to it — sometimes hours later, sometimes days, sometimes (for property damage discovered after winter thaw) months. Industry data shows roughly 80% of FNOL events arrive within 7 days of loss, 95% within 30 days, and a long tail extends to 90+ days.

This collides directly with Spark Structured Streaming's watermark model. A long watermark (90 days) keeps state in memory for every key for that entire window, exploding state-store size and crashing the cluster. A short watermark (24 hours) drops anything older.

Dropping late events is **unacceptable** for insurance — every claim ultimately matters for reserves, fraud, and regulatory reporting.

## Decision

Two-tier handling, with the streaming side handling the common case and the batch side handling the long tail:

**Streaming side (`silver.claim_events`):**
- Watermark: **24 hours** on event-time.
- Late events (event-time older than `now() - watermark`) are **side-output** to a separate Delta table `silver.late_claim_events` rather than dropped.
- Sub-minute fraud signals operate on the streaming table only — they are an *operational* signal, not a reconciled record.

**Batch side (`silver.claim_events_reconciled`):**
- Hourly batch job reads `silver.late_claim_events` and merges into `silver.claim_events_reconciled` with a 90-day reprocess window.
- The reconciled table is the source of truth for downstream finance/actuarial marts.
- Reserve restatement happens at month-end via dbt full refresh of finance marts, with a configurable `RESERVE_AS_OF_DATE` so prior periods can be reproduced.

**Source of truth boundary:**
- Fraud / SIU consume `silver.claim_events` (latency wins; eventually-consistent acceptable).
- Finance / Actuarial / Regulatory consume `silver.claim_events_reconciled` (correctness wins; some lag acceptable).

## Alternatives considered

### Alternative A: Long watermark (90 days) on the streaming job
- **Rejected because:** state explodes — millions of policy keys × 90 days of windowed state crashes any reasonable cluster. Documented Spark anti-pattern.

### Alternative B: Drop late events
- **Rejected because:** unacceptable for insurance; OSFI would have follow-up questions.

### Alternative C: Pure batch — no streaming at all
- **Rejected because:** kills the sub-minute fraud-signal use case (the streaming layer's whole reason to exist).

### Alternative D: Stream-only with side-output but no reconciled table
- **Pros:** Simpler.
- **Rejected because:** finance and actuaries cannot consume an eventually-consistent table directly; the *reconciled* boundary is what makes Polaris auditable.

## Consequences

### Positive
- **Fraud gets sub-minute latency** on the 80–95% of events that arrive on-time.
- **Finance gets correctness** without sacrificing fraud's latency requirement.
- **Reserve restatement is reproducible** — a parameter, not a code change.
- **Regulators see a single, defensible reconciliation boundary.**

### Negative / accepted trade-offs
- **Two tables for what is conceptually one fact.** Mitigated by clear ownership and the reconciled table being the documented source of truth for everything except fraud.
- **90-day reprocess window is configurable but not free** — late events outside 90 days require a manual backfill.
- **Dual code paths** for the MERGE logic (streaming `foreachBatch` and batch `MERGE`). Mitigated by sharing the MERGE helper from `silver_transforms`.

### Mitigations
- `docs/runbooks/late-arriving-90-plus-days.md` (to be written) documents the manual backfill procedure.
- Monitoring alert fires if `silver.late_claim_events` row count exceeds 5% of `silver.claim_events` over a rolling day — that signals a producer-side bug, not a long tail.

## Revisit triggers

- Distribution analysis after 6 months in production shows the 90-day window is wrong (long tail is fatter or thinner than assumed).
- A regulatory change requires reserve restatement on a different cadence (e.g. weekly rather than monthly).
- Snowflake's Snowpipe Streaming or Databricks DLT closes the gap such that one tool can do both jobs without the dual-table split.
