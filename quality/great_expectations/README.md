# Great Expectations — Polaris data quality

> **Status:** rescued from an earlier build and committed in Stage 0. Not run
> yet in this repo. Two things to fix before the first run:
> - The RAW tables these suites check are created in Stage 5.
> - `great_expectations.yml` still connects with `SNOWFLAKE_PASSWORD`. Switch it
>   to key-pair auth (ADR-0008) when Stage 5 wires up the connection.
>
> The Airflow DAG mentioned below arrives in Stage 7.

Two-layer DQ story for the lakehouse:
- **RAW layer** (this directory): expectations about shape, business rules, and
  referential plausibility on data that just landed in Snowflake.
- **STAGING/MARTS layer**: dbt's own `data_tests` (unique / not_null /
  accepted_values / relationships) inside `dbt/models/`.

## Run locally

```bash
cd quality/great_expectations
source ../../.venv/bin/activate         # if you have a local venv
set -a && source ../../.env && set +a
great_expectations checkpoint run raw_polaris
```

Exit code 0 = green, non-zero = at least one expectation failed.

## How Airflow runs it

`polaris_batch_pipeline.py` has a `ge_validate` BashOperator that runs the
same command from the Airflow worker container (volume-mounted at
`/opt/great_expectations`).

## What's in here

```
great_expectations.yml         project config — FluentDatasource for Snowflake POLARIS
expectations/
  raw_customers.json           9 expectations on POLARIS.RAW.RAW_CUSTOMERS
  raw_policies.json            8 expectations on POLARIS.RAW.RAW_POLICIES
  raw_claims.json              7 expectations on POLARIS.RAW.RAW_CLAIMS
checkpoints/
  raw_polaris.yml              runs all three suites; updates data docs
```

## Add a new suite

```bash
great_expectations suite new           # interactive — pick the table, profile rows
```

Then add a `validations:` entry under `checkpoints/raw_polaris.yml` pointing at the new suite.

## Why GE alongside dbt tests (interview answer)

dbt tests run **inside** the warehouse using SQL — fast but limited to
schema-level checks (unique, not_null, accepted_values, relationships).

Great Expectations runs **outside** the warehouse using SQLAlchemy or Spark —
slower but supports richer expectations (regex, distributions, cross-column
pairs, conditional rules, custom Python). It's also the right tool for
file-level checks on Bronze before Snowflake ever sees the data.

Use both. Different layers, different jobs.
