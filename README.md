# Polaris — A Property & Casualty Insurance Claims Lakehouse

> Production-grade P&C insurance claims lakehouse on Azure + Snowflake. Medallion (Bronze/Silver/Gold) with PySpark on Databricks and dbt; real-time FNOL fraud streaming via Kafka + Structured Streaming; orchestrated by Airflow; Terraform IaC; Azure Key Vault + GitHub OIDC; Great Expectations, OpenLineage, and an ADR for every key trade-off.

**Status:** in active development.

---

## Why this exists

A mid-sized P&C carrier I modeled this on runs claims on a legacy mainframe, policy administration on a vendor SaaS, and the Special Investigations Unit (SIU) operates from CSV exports. Three problems compound:

- The CFO cannot reconcile loss reserves to IFRS 17 standards on a T+1 cadence.
- The fraud team is blind until overnight ETL completes.
- Actuaries cannot agree on the grain of a single claim.

Polaris resolves all three by landing raw policy + claims data into ADLS Gen2 (Bronze), conforming it in PySpark on Databricks (Silver) with SCD Type 2 dimensions, streaming First-Notice-of-Loss (FNOL) events through Kafka into a sub-minute fraud signal table, and serving curated marts via dbt + Snowflake (Gold).

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full diagram and narrative.

```
sources → Python ingest → ADLS Bronze → Spark Silver (batch + streaming)
        ↘ Kafka FNOL ↗            ↓
                              Snowflake raw → dbt Gold marts → BI / Streamlit
                                   ↑
                          Great Expectations gates at every layer
                          OpenLineage → Marquez (end-to-end lineage)
                          Airflow orchestrates batch; Spark streaming is long-lived
```

## Quickstart

> Prerequisites: Docker, `uv` (Python package manager), Terraform, Azure CLI, Snowflake account.

```bash
make bootstrap     # install pre-commit hooks + Python deps
cp .env.example .env && $EDITOR .env
make up            # start local Airflow + Kafka + Marquez + Grafana
make seed          # land Synthea + Kaggle samples into Bronze
make stream &      # start the FNOL Kafka producer
make dbt-build     # run the full dbt build against Snowflake dev target
```

Full setup notes will land in `docs/runbooks/local-dev.md` as the build progresses.

## Repo layout

```
polaris-claims-lakehouse/
├── docs/             ADRs, architecture, data model, runbooks
├── infra/            Terraform (Azure + Snowflake) + Docker stack
├── ingestion/        Python CLI for Bronze landing
├── streaming/        Kafka FNOL producer + Spark Structured Streaming jobs
├── databricks/       Notebooks, job bundles, importable Silver transforms wheel
├── dbt/              Staging → intermediate → marts (claims, fraud, finance, actuarial)
├── quality/          Great Expectations checkpoints + YAML data contracts
├── orchestration/    Airflow DAGs
├── adf/              Optional Azure Data Factory trigger demo
├── lineage/          OpenLineage + Marquez config
├── security/         RBAC, secrets policy, threat model
├── consumers/        Streamlit fraud console
└── scripts/          Bootstrap, seed, replay utilities
```

## Architecture Decision Records

Every non-obvious technical choice in Polaris has a written ADR. See [docs/adr/](docs/adr/) for the index.

| # | Title | Status |
|---|---|---|
| [0001](docs/adr/0001-kafka-over-event-hubs.md) | Kafka over Event Hubs for FNOL streaming | Accepted |
| [0002](docs/adr/0002-delta-over-iceberg.md) | Delta Lake over Apache Iceberg for Bronze/Silver | Accepted |
| [0003](docs/adr/0003-snowflake-as-serving.md) | Snowflake as serving layer (not Databricks SQL) | Accepted |
| [0004](docs/adr/0004-scd2-via-merge.md) | SCD Type 2 via Delta MERGE in Silver (not dbt snapshots) | Accepted |
| [0005](docs/adr/0005-late-arriving-fnol.md) | Late-arriving FNOL — bounded watermark + batch reprocess | Accepted |
| [0006](docs/adr/0006-partition-by-event-date-state.md) | Partition fact_claim by event_date + state_code | Accepted |
| [0007](docs/adr/0007-streaming-outside-airflow.md) | Streaming runs as long-lived service outside Airflow | Accepted |
| [0008](docs/adr/0008-secrets-keyvault-oidc.md) | Secrets via Azure Key Vault + GitHub OIDC federation | Accepted |

## Data quality

Two complementary layers, deliberately:

- **Great Expectations** runs at Bronze (file shape, schema, business-key not-null) and Silver (referential integrity, value-set domains). GE failures **hard-stop** the DAG.
- **dbt tests** run at Gold (schema tests + dbt-utils + dbt-expectations + custom singular tests). dbt failures block downstream marts.
- **Data contracts** in [`quality/data_contracts/`](quality/data_contracts/) are negotiated with producers; tests above are the enforcement layer.

## Security

- Secrets live exclusively in Azure Key Vault. `.env` is for local dev only and is gitignored.
- CI uses GitHub OIDC federation to Azure — no long-lived PATs in repository secrets.
- Snowflake authentication uses key-pair (RSA), not passwords.
- RBAC is managed in Terraform under `infra/terraform/snowflake/`.
- See [`security/threat-model.md`](security/threat-model.md) for the STRIDE-lite analysis.

## License

[MIT](LICENSE).
