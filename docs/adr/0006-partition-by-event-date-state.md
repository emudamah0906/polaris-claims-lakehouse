# ADR-0006: Partition fact_claim by event_date + state_code; Z-ORDER on (claimant_id, agent_id)

**Status:** Accepted
**Date:** 2026-05-14
**Decision-makers:** Polaris architecture

## Context

`fact_claim` is the largest table in Polaris and the primary join target for every Gold mart. The partition strategy must:

1. **Prune for the most common query patterns** — state regulator extracts (one state, time-bounded), national finance reports (all states, month-end), fraud lookups (single claimant, recent), actuarial cohort analysis (loss-year × line of business).
2. **Avoid the small-files problem** — too-fine partitioning balloons file metadata and tanks cluster startup.
3. **Survive cardinality** — 50 US states (or 13 Canadian provinces/territories if we localize), 5+ years of history, daily grain.

For Polaris's modeled carrier (US P&C synthetic data via Synthea), 50 states × 5 years × 365 days = ~91k partitions over the table's lifetime. Per-day per-state row counts vary 100x between California and Wyoming — partition skew is real.

## Decision

```sql
PARTITIONED BY (event_date DATE, state_code STRING)
```

Plus periodic maintenance:

```sql
OPTIMIZE silver.fact_claim ZORDER BY (claimant_id, agent_id);   -- weekly
VACUUM silver.fact_claim RETAIN 168 HOURS;                       -- monthly, after 7-day audit window
```

Spark write config: `spark.sql.sources.partitionOverwriteMode = dynamic` so partial-day reprocessing only touches affected partitions.

## Alternatives considered

### Alternative A: `PARTITIONED BY (event_date)` only
- **Pros:** Simpler; ~1.8k partitions over 5 years.
- **Cons:** State-by-state regulator queries (the most common ad-hoc query at any US carrier) scan the entire day. State-level fraud rings don't prune.
- **Rejected because:** state-level pruning is a recurring query pattern; the metadata cost of adding `state_code` is paid for many times over.

### Alternative B: `PARTITIONED BY (event_date, product_line)`
- **Pros:** Symmetrical with the actuarial query mix.
- **Cons:** Only ~5 product lines (auto, home, commercial, life, specialty) — low pruning value vs storage cost. Heavy data skew (auto >> specialty). State regulators (the more common consumer) get no benefit.
- **Rejected because:** state cardinality + state-as-query-predicate beats product line on this workload.

### Alternative C: Hash partitioning by `claim_id`
- **Pros:** Eliminates skew.
- **Cons:** Destroys time-range pruning — every "last 7 days" query becomes a full scan.
- **Rejected because:** time-range queries dominate the workload.

### Alternative D: Liquid Clustering (Delta) instead of partitioning
- **Pros:** No partition design at all; clusters data by chosen columns; auto-evolves.
- **Cons:** Recent feature — interview defensibility is weaker; still requires choosing the cluster keys correctly.
- **Decision:** layer Z-ORDER on top of partitioning rather than replace partitioning. Reconsider Liquid Clustering once it has 18+ months of production maturity.

## Consequences

### Positive
- **State + date pruning** for the dominant query pattern.
- **Z-ORDER on (claimant_id, agent_id)** accelerates the secondary access patterns: SIU pulls all claims by claimant; agent-performance reports pull by agent.
- **Dynamic partition overwrite** lets a partial-day reprocess (common during late-arriving reconciliation) touch only the affected `(date, state)` partitions.

### Negative / accepted trade-offs
- **~91k partitions over 5 years.** High but manageable on Delta with Unity Catalog metadata. Mitigated by weekly OPTIMIZE.
- **Skew between high- and low-volume states** means California partitions are 50x larger than Wyoming partitions. Mitigated by Spark's adaptive query execution (AQE) at read time.
- **Adding a new partition column later requires a rewrite.** Mitigated by getting it right now and documenting the revisit trigger below.

### Mitigations
- Weekly maintenance Databricks job: `OPTIMIZE` + Z-ORDER + `VACUUM` (with the 7-day retention floor for time-travel).
- Monitoring on `_delta_log` size — if file count per partition exceeds 1000, alert and trigger ad-hoc OPTIMIZE.
- Cluster sizing for batch Silver jobs uses `spark.sql.adaptive.enabled = true` to handle the partition-size skew.

## Revisit triggers

- **Cardinality of `state_code` changes** — international expansion adds country code; revisit whether `(country_code, event_date, state_code)` makes sense.
- **Liquid Clustering matures** to 18+ months of production runtime on Databricks; re-evaluate replacing partitioning.
- **Storage cost of small files** dominates query cost in monitoring — consider promoting from `event_date` (daily) to `event_month` partition.
