# ADR-0004: SCD Type 2 via Delta MERGE in Silver (not dbt snapshots in Gold)

**Status:** Accepted
**Date:** 2026-05-14
**Decision-makers:** Polaris architecture

## Context

Polaris must track historical changes to dimensions that drive every fact join — most notably `dim_policyholder` (address, marital status, occupation, risk class, agent assignment) and `dim_policy` (coverage limits, deductibles, endorsements). Both change frequently and both are queried point-in-time by actuaries and regulators.

The choice is *where* in the architecture SCD2 lives:

- **In Silver**, owned by Spark MERGE on Delta tables.
- **In Gold**, owned by `dbt snapshots` after the data lands in Snowflake.
- **As daily full snapshots** retained forever.
- **SCD Type 3** with a small fixed history of prior values.

The downstream consumers are unforgiving: actuarial reserve restatements need full history; fraud needs current values + the prior value at the time of the claim event; regulators (OSFI, provincial superintendents) audit *as-of* point-in-time states.

## Decision

Implement **SCD Type 2 in Silver via Delta MERGE**, owned by the `silver_transforms` PySpark library.

Schema for every SCD2 dimension:
- `<dim>_sk` — surrogate key (BIGINT, generated)
- `<dim>_id` — natural / business key
- `effective_from` (TIMESTAMP, inclusive)
- `effective_to` (TIMESTAMP, exclusive; NULL = current)
- `is_current` (BOOLEAN, denormalized for query perf)
- `change_hash` (SHA-256 of all tracked attributes — used to skip no-op writes)
- `_loaded_at` (TIMESTAMP, audit)

Intra-day changes collapse to **last-write-wins per source `event_timestamp`**, since the carrier's claims-of-record is event-time, not processing-time.

## Alternatives considered

### Alternative A: dbt snapshots in Gold
- **Pros:** Declarative; single tool (dbt) owns dimensional history; clean test story.
- **Cons:** Snapshots run *after* data lands in Snowflake — too late. Silver fact tables built on Databricks need the SCD2 dim to do as-of joins for `fact_claim` to `dim_policyholder`. If SCD2 lives in Snowflake, we either duplicate the logic in Spark (inconsistency risk) or push fact construction down to Snowflake (defeats the point of Silver).
- **Rejected because:** the consumer of SCD2 history is *upstream* of dbt. Ownership belongs where the join happens.

### Alternative B: Daily full snapshot tables
- **Pros:** Trivial to implement (`INSERT OVERWRITE` daily).
- **Cons:** Storage explodes — 10M policyholders × 365 days = 3.65B rows for what is mostly identical data. Point-in-time joins become expensive scans rather than indexed lookups.
- **Rejected because:** storage and query cost are unjustifiable when most policyholder rows don't change daily.

### Alternative C: SCD Type 3 (fixed history columns)
- **Pros:** Smaller storage; simple queries.
- **Cons:** Loses history beyond 1–2 prior values. Actuarial reserve restatements over a 5-year horizon and OSFI audit trails need full history.
- **Rejected because:** insufficient for regulatory and actuarial requirements.

## Consequences

### Positive
- **Idempotent backfills.** Replaying a day of source events produces the same SCD2 state. Achieved via `change_hash` — repeated MERGE of the same logical row is a no-op.
- **Atomic batch updates.** Spark MERGE updates dim + writes fact in the same transaction boundary (per table) — no risk of fact joining to a stale dim version mid-batch.
- **Change Data Feed** on Silver dims feeds incremental dbt models in Gold without re-scanning the dim.
- **Reproducible point-in-time queries** via `valid_from <= as_of_ts < coalesce(valid_to, '9999-12-31')`.

### Negative / accepted trade-offs
- **MERGE is more code than `INSERT OVERWRITE`.** Mitigated by a generic `apply_scd2(target, source, business_keys, tracked_attrs)` helper in `silver_transforms` so the per-dim job is a few lines.
- **Out-of-order source events** — a late-arriving "old" change can land after a newer one. Mitigated by ordering by `source_event_timestamp` within MERGE and defining the conflict resolution explicitly: newest `source_event_timestamp` wins; older lands as a closed historical row in the right slot.

### Mitigations
- The generic SCD2 helper has property-based tests in `databricks/libraries/silver_transforms/tests/test_scd2.py` covering: insert, update, no-op, late-arriving, intra-day-multiple-changes.
- The runbook `docs/runbooks/dim-reload.md` (to be written) documents how to safely reload a dim from history.

## Revisit triggers

- If a dim becomes too hot for MERGE on a small cluster, consider partitioning the dim itself by hash bucket of business key.
- If dbt 1.8+ snapshots gain change-data-capture-style efficiency that closes the gap with Spark MERGE, re-evaluate ownership for Gold-only dims (reference data only).
