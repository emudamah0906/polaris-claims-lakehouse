# Polaris — Architecture

## End-to-end flow

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  SOURCES                                                                              │
│   Synthea synthetic claims (CSV)                                                      │
│   Kaggle auto-insurance fraud (CSV)                                                   │
│   Synthetic FNOL Producer (Python — controlled rate, late-arrival, out-of-order)     │
└────────────┬───────────────────┬──────────────────────────┬─────────────────────────┘
             │ batch (daily)     │ batch (one-shot seed)    │ stream (continuous)
             ▼                   ▼                          ▼
   ┌────────────────────────────────────────┐     ┌─────────────────────────────────┐
   │  Python Ingestion (Docker image)       │     │  Kafka 3-broker cluster (Docker)│
   │   - retries, schema sniff on landing   │     │   topic: fnol.events.v1         │
   │   - idempotent writes                  │     │   Confluent Schema Registry     │
   └─────────────┬──────────────────────────┘     └────────────┬────────────────────┘
                 │                                              │
        ┌────────▼──────────────────────────────────────────────▼──────────────┐
        │  AZURE ADLS GEN2 — BRONZE                                            │
        │   abfss://bronze@polarisstg.dfs/insurance/{src}/yyyy=/mm=/dd=/       │
        │   Delta format, append-only, partitioned by ingest_date              │
        │   ADF copy job demos on-prem SFTP → ADLS landing (optional trigger)  │
        └────────────────────────────┬─────────────────────────────────────────┘
                                     │
              ┌──────────────────────▼──────────────────────────────┐
              │  GREAT EXPECTATIONS — Bronze checkpoints            │
              │   row count, file shape, business-key not-null      │
              └──────────────────────┬──────────────────────────────┘
                                     ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  DATABRICKS / SPARK  —  SILVER                                            │
   │   batch jobs:  dim_policyholder (SCD2 via MERGE), dim_policy, dim_agent  │
   │                fact_claim, fact_payment                                   │
   │   streaming:   readStream(Kafka) → join dim_policy → silver.claim_events │
   │                watermark 24h, dedup on event_id, foreachBatch → Delta    │
   │   schema evolution: Delta mergeSchema, contract enforced upstream        │
   │   partition: fact_claim by event_date + state_code (low cardinality)     │
   └──────────────────────────────┬───────────────────────────────────────────┘
                                  │
              ┌───────────────────▼─────────────────────────┐
              │  GREAT EXPECTATIONS — Silver checkpoints    │
              │   referential integrity, PK uniqueness,     │
              │   value-set domains (peril, status)         │
              └───────────────────┬─────────────────────────┘
                                  │  Snowpipe auto-ingest (ADLS Event Grid notifications)
                                  ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  SNOWFLAKE — RAW + STAGING                                                │
   │   external stage on ADLS via storage integration (no SAS in code)         │
   │   warehouses: WH_LOAD (XS, autosuspend 60s) / WH_TRANSFORM (S) / WH_BI    │
   └──────────────────────────────┬───────────────────────────────────────────┘
                                  ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  dbt CORE — GOLD MARTS                                                    │
   │   staging → intermediate → marts/{claims, fraud, finance, actuarial}     │
   │   snapshots/ for slowly-changing reference (state-tax tables, peril map) │
   │   tests: dbt_utils + dbt-expectations + custom (loss-ratio sanity)       │
   │   exposures.yml → Power BI dashboards + Streamlit fraud console          │
   │   freshness SLA per source                                                │
   └──────────────────────────────┬───────────────────────────────────────────┘
                                  ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  CONSUMERS                                                                │
   │   - Streamlit fraud console (live from silver.claim_events via Snowflake)│
   │   - Power BI / Metabase finance + actuarial dashboards                   │
   │   - Reverse-ETL stub (write back fraud_score to claims system — JSON)    │
   └──────────────────────────────────────────────────────────────────────────┘
```

## Cross-cutting concerns

### Orchestration
Airflow (Docker) owns the batch DAGs:
`bronze_ingest → silver_batch → ge_silver → snowflake_load → dbt_build → ge_gold → notify`.
The Spark Structured Streaming job is **not** in Airflow — it runs as a long-lived Databricks job. Airflow only checks its heartbeat (see [ADR-0007](adr/0007-streaming-outside-airflow.md)).

### Lineage
OpenLineage emitters are wired into Spark, Airflow, and dbt. All events flow into Marquez (Docker), producing a single graph from FNOL producer → BI tile.

### Security
- Azure Key Vault holds every secret (ADLS keys, Snowflake private key, Databricks OAuth client secret).
- GitHub Actions authenticates to Azure via OIDC federation — no PATs in repository secrets.
- Snowflake uses key-pair authentication; no passwords anywhere.
- RBAC roles are managed in Terraform under `infra/terraform/snowflake/`.
- See [`security/threat-model.md`](../security/threat-model.md) for the STRIDE-lite analysis.

### CI/CD
GitHub Actions runs:
- `ci.yml` — pre-commit (ruff, sqlfluff, terraform-fmt, gitleaks) + pytest on every PR.
- `dbt-ci.yml` — `dbt build` against an ephemeral CI Snowflake schema per PR.
- `terraform.yml` — `terraform plan` on PR; `apply` on merge to main with manual gate.
- `docker-build.yml` — build & push Airflow + ingestion images to GHCR.
- `dbt-prod.yml` — `dbt build --target prod` on merge to main.

### Monitoring
- Airflow SLA misses → Slack webhook.
- Great Expectations failures → hard-fail the DAG (not warn).
- Snowflake `QUERY_HISTORY` → cost dashboard via dbt analysis.
- Kafka consumer lag → Prometheus → Grafana (Docker).

### Data quality — two layers, deliberately
| Layer | Tool | What it catches | Failure action |
|---|---|---|---|
| Bronze | Great Expectations | File shape, schema, business-key not-null | Reject load; alert |
| Silver | Great Expectations | Referential integrity, PK uniqueness, value-set domains | Hard-stop DAG |
| Gold | dbt tests | Schema tests, dbt-expectations, custom SQL (loss-ratio sanity) | Block downstream marts |
| All | YAML data contracts in [`quality/data_contracts/`](../quality/data_contracts/) | The negotiated layer between producer + consumer | Source of truth for the tests above |

## Key trade-offs

Every non-obvious technical choice is captured in an [Architecture Decision Record](adr/). The ADR index lives in the [README](../README.md#architecture-decision-records).
