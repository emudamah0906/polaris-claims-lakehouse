# dbt: staging and marts on Snowflake (Stage 6)

Reads `POLARIS.RAW` (loaded by COPY INTO from ADLS in Stage 5) and builds
typed staging views and mart tables. Runs as `POLARIS_SVC` with
`POLARIS_DBT_ROLE`, never ACCOUNTADMIN.

> **Status:** built and tested 20 Oct 2026. `dbt build`: PASS=60, 0 errors.
> Every count below was worked out from the Bronze CSVs before the run.

## Run it

```bash
cd ~/Desktop/Career-Hub/Projects/polaris-claims-lakehouse
make dbt-setup     # once: Python 3.12 venv, dbt-snowflake, dbt_utils
make dbt-build     # models + all tests
```

Needs `.env` at the repo root (gitignored, see `.env.example`): account,
`POLARIS_SVC`, and the full path to `~/.snowflake/polaris_svc_rsa.p8`.

dbt has its own venv in `dbt/.venv.nosync` because dbt 1.11 doesn't run on
Python 3.14, which the root venv uses.

## What it builds

```
RAW (VARCHAR, PII)         STAGING (views, typed, no direct PII)      MARTS (tables)
customers       3,000  →   stg_customers       3,000              →   dim_customer                 3,000
policies        5,000  →   stg_policies        5,000              →   dim_policy                   5,000
claims         10,000  →   stg_claims         10,000              →   fct_claims                  10,000
claim_payments 11,203  →   stg_claim_payments 11,203              →   fct_claim_payments          11,203
                                                                      finance_claims_paid_monthly     71
                                                                      fraud_claim_signals          1,948
```

| Mart | Grain | Answers |
|---|---|---|
| `fct_claims` | claim | Paid to date by type, report lag, late FNOL (480 claims) |
| `fct_claim_payments` | payment | Payments with product and claim type |
| `finance_claims_paid_monthly` | month × product | Claims paid by indemnity, expense, recovery. Total $1,419,914,985.10 |
| `fraud_claim_signals` | claim | Claims with a signal: loss within 30 days of policy start, late FNOL, model score ≥ 0.7. 1,830 with one, 117 with two, 1 with three |
| `dim_policy`, `dim_customer` | policy, customer | Current version; customers carry policy counts (557 have none) |

## Tests (60)

- **Keys and links:** unique and not_null on every key; relationships from
  payments to claims, claims to policies and policies to customers.
- **Did every cast work:** not_null on each TRY_ cast column. A value that
  couldn't convert becomes NULL and fails here, instead of breaking the load.
- **Allowed values:** statuses, product types and payment types.
- **Reconciliation** (`tests/`):
  - `assert_raw_to_staging_row_counts`: keys in RAW = rows in staging, per table
  - `assert_payments_reconcile`: RAW total = payments fact = finance mart =
    sum of `fct_claims.total_paid`, to half a cent
  - `assert_paid_claims_fully_paid`: closed and paid claims are paid in full;
    open and denied claims have no payments

## Choices worth defending

- **PII stops at RAW.** Analysts can read STAGING, so staging drops SIN, full
  birth date, name, email, phone and street address (it keeps birth year and
  postal area). RAW is readable by the loader and dbt roles only. A masking
  policy on RAW is on the Stage 7 list.
- **Schemas are Terraform's.** `macros/generate_schema_name.sql` makes
  `+schema: staging` mean exactly `POLARIS.STAGING`. dbt's default would build
  `STAGING_STAGING`-style names and need CREATE SCHEMA, which the dbt role
  doesn't have.
- **Grants come for free.** The analyst role got SELECT on every new mart
  through Stage 1's future grants. Nobody ran a GRANT after dbt.
- **DECIMAL for money,** never FLOAT, so totals match to the cent.
- **Dedup in staging** with `QUALIFY ROW_NUMBER()` on the key, newest load
  first. If a file is ever loaded twice, the marts don't double.
- **No dbt snapshots.** Policy history (SCD2) belongs to Silver with MERGE
  (ADR-0004). `dim_policy` is the current version until Stage 3.

## Known gap: claim amounts

The generator multiplies claim amounts by 100, so a typical auto claim is
about $180k against a $1,900 premium. That gives loss ratios of 81× (auto)
and 308× (property), and 74% of claims sit at 70%+ of their coverage limit.
So there's no actuarial loss-ratio mart and no "near the limit" fraud signal
until the generator is fixed. Counts, keys and payment reconciliation are
unaffected.
