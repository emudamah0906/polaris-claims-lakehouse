# ADR-0002: Use Delta Lake over Apache Iceberg for Bronze/Silver storage

**Status:** Accepted
**Date:** 2026-05-14
**Decision-makers:** Polaris architecture

## Context

Bronze and Silver in Polaris need an open-table format providing ACID writes, time-travel, schema evolution, optimized point-in-time reads, and efficient MERGE for SCD2. The chosen format must integrate cleanly with our compute (Databricks Spark for batch + streaming) and our serving layer (Snowflake reading external tables for late-arriving reconciliation).

The candidate formats are mature and feature-comparable on paper. The decision is governed by *integration cost in our specific stack*, not by feature checklists.

## Decision

Use **Delta Lake 3.x** as the storage format for all Bronze and Silver tables, written from Databricks Spark, with `mergeSchema` enabled at the Bronze landing boundary and Change Data Feed (CDF) enabled on Silver dimensions.

## Alternatives considered

### Alternative A: Apache Iceberg
- **Pros:** Catalog-agnostic by design; first-class Trino/Flink/Snowflake/BigQuery write support; hidden partitioning removes a class of partition-design mistakes; partition evolution without rewriting data.
- **Cons:** Databricks Iceberg *write* support requires Unity Catalog Managed Iceberg (recent, with feature gaps versus Delta); the ecosystem of optimization tools (auto-compaction, Liquid Clustering, predictive I/O) is Delta-first on Databricks.
- **Rejected because:** Polaris's compute is Databricks-only. Choosing Iceberg trades away first-party Databricks features (Liquid Clustering, predictive I/O, deletion vectors) for portability we will not exercise. If a second engine ever writes the lake, this decision should be revisited.

### Alternative B: Apache Hudi
- **Pros:** Strong incremental ingestion model; record-level upserts via merge-on-read.
- **Cons:** Smaller community in the FS/insurance space; weaker tooling in our chosen ecosystem; less common in senior-DE interview ground.
- **Rejected because:** the upsert advantage doesn't outweigh the ecosystem cost in our stack.

### Alternative C: Plain Parquet + Hive partitions
Not seriously considered. No ACID, no concurrent writers, no time-travel — fails the SCD2 and reproducibility requirements.

## Consequences

### Positive
- **MERGE-based SCD2** runs efficiently with Delta's optimized join + write planning.
- **Time-travel** lets us rerun any historical Silver build deterministically — critical for reproducible IFRS 17 loss reserve restatements.
- **Change Data Feed** on dimensions feeds downstream incremental dbt models without scanning the whole table.
- **Snowflake reads external Delta tables natively** since Iceberg/Delta interop landed — we keep Delta in the lake and still serve from Snowflake.

### Negative / accepted trade-offs
- **Vendor coupling** to Databricks. If we ever migrate compute off Databricks, conversion is non-trivial (delta-rs helps for read; writes are harder).
- **Partition evolution** requires rewriting data — Iceberg would do this transparently. Mitigated by getting partition design right up-front (see [ADR-0006](0006-partition-by-event-date-state.md)).

### Mitigations
- Code that reads/writes Delta is isolated in the `silver_transforms` library so a future format swap is one library swap.
- We avoid Delta-only DML extensions where a vendor-portable equivalent exists.

## Revisit triggers

- A second compute engine (Trino, Flink, Spark-on-K8s without Databricks) needs to write the lake.
- Databricks pricing or feature direction changes such that Iceberg becomes the strategic format on the platform.
- Snowflake's external Delta read performance regresses meaningfully versus Iceberg.
