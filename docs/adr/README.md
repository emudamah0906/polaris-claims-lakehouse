# Architecture Decision Records

This directory holds one Markdown file per non-obvious technical decision made in Polaris. Every ADR follows the [template](0000-template.md).

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-kafka-over-event-hubs.md) | Use Apache Kafka (Docker) over Azure Event Hubs for FNOL streaming | Accepted |
| [0002](0002-delta-over-iceberg.md) | Use Delta Lake over Apache Iceberg for Bronze/Silver storage | Accepted |
| [0003](0003-snowflake-as-serving.md) | Snowflake as the serving layer (not Databricks SQL) | Accepted |
| [0004](0004-scd2-via-merge.md) | SCD Type 2 via Delta MERGE in Silver (not dbt snapshots in Gold) | Accepted |
| [0005](0005-late-arriving-fnol.md) | Late-arriving FNOL — bounded streaming watermark + batch reprocess | Accepted |
| [0006](0006-partition-by-event-date-state.md) | Partition fact_claim by event_date + state_code; Z-ORDER on (claimant_id, agent_id) | Accepted |
| [0007](0007-streaming-outside-airflow.md) | Spark Structured Streaming runs as a long-lived service outside Airflow | Accepted |
| [0008](0008-secrets-keyvault-oidc.md) | Secrets via Azure Key Vault; CI auth via GitHub OIDC; no long-lived credentials | Accepted |

## How to write a new ADR

1. Copy [`0000-template.md`](0000-template.md) to `NNNN-short-title.md`.
2. Fill every section. Be specific about *what was rejected and why* — that section is what an interviewer reads.
3. Set `Status: Accepted` only after the decision is implemented in code.
4. Update the index above and the table in the root [`README.md`](../../README.md).

## Why ADRs

ADRs are the most senior-engineering signal in this repository. Tools (Kafka, dbt, Snowflake) commodify; *judgment about when to use each* is what staff/principal engineers are paid for. Every ADR here is a written, defendable answer to a question an interviewer will ask.
