# Polaris: an insurance claims data platform on Azure, Databricks and Snowflake

Polaris takes data from a car and home insurer's systems (customers, policies, claims, claim
payments and body-shop repair estimates), lands it in a data lake, cleans it, and builds tables
the claims, finance and fraud teams can report from.

It runs on real cloud accounts (Azure, Azure Databricks, Snowflake), not just on a laptop. Every
stage is built and tested on its own branch and pull request. A stage is only marked done after
it has run against real infrastructure.

**Honest scope:** ingestion through to the reporting tables is built and runs every day under
Airflow. Kafka streaming, CI/CD, Great Expectations checks, lineage and dashboards are designed
but not built yet. The table below shows exactly where each part stands.

## How one day of data flows

```
Postgres (claims system) ──Python extract, changed rows only──┐
                                                               ├─> ADLS Bronze ─> Snowflake RAW ─> dbt marts
Vendor CSV drop (landing) ──ADF copy + row-count check────────┘        │          (COPY INTO)       (claims,
                                                                        │                            finance,
                                                                        └─> Databricks Silver         fraud)
                                                                            (history of policy changes)

Airflow runs the whole day in order and opens a GitHub issue when a step fails.
```

- **Bronze** = the raw files exactly as they arrived, kept by date.
- **Silver** = cleaned data, with a full history of every policy change (SCD Type 2).
- **Marts** = final tables for reporting, built and tested with dbt in Snowflake.

## What is built

| Stage | What it does | Status |
|---|---|---|
| 0 | Clean up the repo: Makefile, README, saved data-quality suites | Done |
| 1 | Snowflake set up with Terraform: database, schemas, warehouses, three roles, a credit limit | Done 15 Oct 2026 (39 resources) |
| 2 | Python tool that lands each day's files in ADLS Bronze | Done 20 Oct 2026. Re-running a day gives byte-identical files |
| 2b | Pull only changed rows from Postgres, using an `updated_at` watermark | Done 20 Oct 2026. Day 2 pulled 0 / 385 / 149 / 100 changed rows, not full tables. See [ingestion/README.md](ingestion/README.md) |
| 2c | Azure Data Factory copies the vendor file to Bronze and checks the row count | Done 20 Oct 2026. Good day: 51 rows copied = 51 in the manifest. Bad manifest (52): the copy was deleted and the run failed on purpose. See [docs/runbooks/stage-2c-adf.md](docs/runbooks/stage-2c-adf.md) |
| 3 | Silver on Azure Databricks: PySpark, Unity Catalog, policy history in one MERGE | Done 21 Oct 2026. Re-running a day changes 0 rows. A source column change was caught and logged. See [databricks/](databricks/) |
| 4 | Streaming: new claims (FNOL) through Kafka into Spark Structured Streaming | Not started. The local Kafka stack runs |
| 5 | Snowflake reads Bronze from ADLS (storage integration, external stage, COPY INTO) | Done 20 Oct 2026. RAW 3,000 / 5,000 / 10,000 / 11,203 rows; re-running loads 0 files |
| 6 | dbt models and tests for claims, finance and fraud marts | Done 20 Oct 2026. Totals reconcile from RAW to marts to the cent. See [dbt/README.md](dbt/README.md) |
| 7 | Airflow runs the daily pipeline | In progress. DAG `polaris_daily` (8 tasks) is built and has run 10 business days. Great Expectations gates, lineage and dashboards not built |

### The 10-day production run

To practise running this like a real production job, Airflow ran ten business days
(19-28 Oct 2026) back to back in one session. Each run was given its business date as a
parameter, the same way a backfill works. Nothing in the pipeline reads the clock, so re-running
any day gives the same result.

When a step failed, Airflow opened a GitHub issue. Those issues are worked like on-call tickets:
find the cause, fix it, re-run, and write a short root-cause note.

## Run it yourself

You need Docker, [uv](https://docs.astral.sh/uv/), Terraform, the Azure CLI and a Snowflake account.

```bash
make bootstrap                 # install Python tools and pre-commit hooks
cp .env.example .env           # then fill in your Snowflake account and key path
make up                        # local Docker stack (Postgres, Kafka)
make tf-init && make tf-plan   # Snowflake Terraform; read infra/terraform/snowflake/README.md first
```

One day end to end:

```bash
uv run polaris-ingest run --ingest-date 2026-10-16 --backend azure --account <storage-account>
# then run ingestion/snowflake/load_raw.sql as POLARIS_LOADER_ROLE (COPY INTO RAW)
make dbt-setup && make dbt-build
```

The whole day under Airflow: `orchestration/airflow.sh standalone`, then open localhost:8080.

## What is in each folder

```
polaris-claims-lakehouse/
├── adf/              Data Factory pipeline, datasets and linked service as JSON (deployed by scripts/deploy_adf.sh)
├── databricks/       Silver job and its Asset Bundle
├── dbt/              Staging, intermediate and mart models, with tests
├── docs/             Architecture, design decisions (ADRs), runbooks
├── infra/            Terraform (Azure, Databricks, Snowflake) and the Docker stack
├── ingestion/        Python tool for Bronze, Postgres extract, Snowflake load SQL
├── orchestration/    Airflow DAGs and the start script
├── quality/          Great Expectations suites (not yet wired into the pipeline)
├── scripts/          Data generator, ADF deploy and run helpers
├── streaming/        Stage 4 (empty for now)
├── consumers/        Fraud dashboard (planned)
├── lineage/          OpenLineage / Marquez (planned)
└── security/         Threat model (planned)
```

## Design decisions

Each important choice has a short written record (ADR) with the options and trade-offs. See
[docs/adr/](docs/adr/).

| # | Decision |
|---|---|
| [0001](docs/adr/0001-kafka-over-event-hubs.md) | Kafka instead of Event Hubs for new-claim streaming |
| [0002](docs/adr/0002-delta-over-iceberg.md) | Delta Lake instead of Iceberg for Bronze and Silver |
| [0003](docs/adr/0003-snowflake-as-serving.md) | Snowflake serves the reports, not Databricks SQL |
| [0004](docs/adr/0004-scd2-via-merge.md) | Policy history (SCD2) with a Delta MERGE in Silver, not dbt snapshots |
| [0005](docs/adr/0005-late-arriving-fnol.md) | How to handle late-arriving claims |
| [0006](docs/adr/0006-partition-by-event-date-state.md) | Partition the claims fact by event date and province |
| [0007](docs/adr/0007-streaming-outside-airflow.md) | Streaming runs as its own long-running service, not inside Airflow |
| [0008](docs/adr/0008-secrets-keyvault-oidc.md) | Secrets in Azure Key Vault; CI logs in to Azure with GitHub OIDC |

## Data quality today

- **dbt tests** on every model: keys unique and not null, valid values, relationships, and a
  reconciliation test that RAW totals match the marts.
- **ADF row-count check**: Bronze never keeps a vendor file shorter or longer than its manifest.
- **Silver load audit**: every Databricks load records row counts and flags unexpected column changes.
- Great Expectations suites exist in `quality/` but don't stop the pipeline yet (Stage 7).

## Security today

- No passwords or keys in git. `.env`, Terraform variable files and private keys stay local.
- Snowflake logins use key pairs, not passwords. Roles and grants are in Terraform.
- Data Factory reads and writes storage as its own managed identity, with read-only access to
  landing and write access only to Bronze. No storage keys are pasted anywhere.
- Personal fields (SIN, date of birth) are dropped in dbt staging; a masking policy is planned.
- Key Vault and GitHub OIDC (ADR 0008) are designed, not built yet.

## Known limits

- The data is synthetic. Claim amounts are inflated by the generator, so loss ratios are not
  realistic. There is no actuarial mart until that is fixed (see [dbt/README.md](dbt/README.md)).

## License

[MIT](LICENSE).
