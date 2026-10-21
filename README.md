# Polaris — A Property & Casualty Insurance Claims Lakehouse

> **Scope:** part built, part design. Running today on real Azure and Snowflake (20 Oct 2026):
> Python ingest → ADLS Bronze → Snowflake RAW (storage integration + COPY INTO) → dbt staging
> and marts, all provisioned with Terraform, 60 dbt tests passing. Databricks Silver, Kafka
> streaming, ADF, Postgres CDC and Airflow are designed (ADRs) but not built. See the table.

> Production-grade P&C insurance claims lakehouse on Azure + Snowflake. Medallion (Bronze/Silver/Gold) with PySpark on Databricks and dbt; real-time FNOL fraud streaming via Kafka + Structured Streaming; orchestrated by Airflow; Terraform IaC; Azure Key Vault + GitHub OIDC; Great Expectations, OpenLineage, and an ADR for every key trade-off.

## Build progress

Built so far: 0, 1, 2, 2b, 2c, 3, 5, 6 and most of 7, so data runs end to end from the Python CLI to dbt marts in
Snowflake. Stage 5 was moved ahead of 2b, 2c, 3 and 4 to get there first.

The design is complete (8 ADRs). The build follows the seven-stage plan, plus
2b and 2c to cover more ingestion patterns, one stage per pull request. A stage is marked done only after it has run against
real infrastructure.

| Stage | What | Status |
|---|---|---|
| 0 | Repo hygiene: rescued GE suites, Makefile and README fixes | Done |
| 1 | Foundation: Snowflake Terraform (database, schemas, warehouses, RBAC, credit cap), local Kafka stack, ADRs | Done: applied 15 Oct 2026, 39 resources, re-plan clean |
| 2 | Bronze ingestion: Python CLI → ADLS (file-drop batch) | Done: landed in ADLS 20 Oct 2026, 4 tables + `_SUCCESS`, re-run byte-identical |
| 2b | Incremental extract: Postgres claims system → Bronze with an `updated_at` watermark | Done: 20 Oct 2026, day 2 pulled only 0 / 385 / 149 / 100 changed rows, retry byte-identical. See [ingestion/README.md](ingestion/README.md) |
| 2c | Azure Data Factory: landing → Bronze copy with a row-count check | Done: 20 Oct 2026, factory in Terraform, pipeline as JSON in `adf/`. 16 Oct copied 51 = manifest 51; 17 Oct bad manifest (52) deleted the copy and failed the run. See [docs/runbooks/stage-2c-adf.md](docs/runbooks/stage-2c-adf.md) |
| 3 | Silver: PySpark SCD2 on Databricks | Done: 21 Oct 2026, Azure Databricks (Premium, Unity Catalog, serverless jobs) via Terraform + Asset Bundle. 10 business days loaded; policies SCD2 in one MERGE; rerun changes 0 rows; schema drift flagged on 27-28 Oct. See [databricks/](databricks/) |
| 4 | Streaming: Kafka FNOL producer + Spark Structured Streaming | Not started (Kafka stack runs locally) |
| 5 | Snowflake landing: COPY INTO from the ADLS external stage | Done: 20 Oct 2026, storage integration + external stage, RAW 3,000 / 5,000 / 10,000 / 11,203, re-run loads 0 files |
| 6 | dbt staging + marts (claims, finance, fraud) | Done: 20 Oct 2026, `dbt build` PASS=60, reconciliation RAW → marts to the cent. See [dbt/README.md](dbt/README.md). Actuarial mart waits on a generator fix |
| 7 | Orchestration, data quality, lineage, BI | In progress: Airflow DAG `polaris_daily` (8 tasks) ran business days 19-28 Oct with failure tickets on GitHub Issues. Lineage, Great Expectations and BI not built |

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
make up            # start local Kafka + Schema Registry
make tf-init       # Snowflake Terraform; see infra/terraform/snowflake/README.md first
make tf-plan
```

End to end today (Stages 2, 5, 6):

```bash
uv run polaris-ingest run --ingest-date 2026-10-16 --backend azure --account polaris599i8o
# then ingestion/snowflake/load_raw.sql as POLARIS_LOADER_ROLE (COPY INTO RAW)
make dbt-setup && make dbt-build
```

Targets for later stages (`seed`, `stream`, `ge-run`) are in the Makefile
already but won't work until their stage lands.

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
- A STRIDE-lite threat model is planned for `security/threat-model.md`.

## License

[MIT](LICENSE).
