# Polaris — local data directory

This folder holds **generated** data for local dev and CI. Everything under
`data/raw/`, `data/staged/` and `data/bronze/` is gitignored and can be rebuilt
from the generator in `ingestion/src/polaris_ingest/sources/synthetic.py`.

## Land a day in Bronze (Stage 2)

```bash
# Day-1 baseline
uv run polaris-ingest run --ingest-date 2026-10-16

# Day-2 refresh of that baseline (premium bumps, cancellations, new claims,
# payments). Drives the SCD2 demo in Stage 3.
uv run polaris-ingest run --ingest-date 2026-10-17 --day 2
```

Files land in `data/bronze/<table>/year=YYYY/month=MM/day=DD/part-00000.csv`,
with an empty `data/bronze/_markers/ingest_date=YYYY-MM-DD/_SUCCESS` written
last.

For a quick flat copy instead, `uv run scripts/generate_polaris_data.py --as-of 2026-10-16`
writes the same tables to `data/raw/`.

## What gets produced (seed 42)

| Table | Day 1 (2026-10-16) | Day 2 (2026-10-17) | Notes |
|---|---:|---:|---|
| customers      |  3,000 |  3,000 | PII: SIN, date of birth, address, phone |
| policies       |  5,000 |  5,000 | AUTO 60% / PROPERTY 40%. Day 2 changes ~8% of them |
| claims         | 10,000 | 10,050 | 480 late-arriving FNOL (4.8%), 317 fraud-flagged (3.2%) |
| claim_payments | 11,203 | 11,303 | 1-3 per CLOSED/PAID claim. Day 2 pays off 100 open claims |

## Why the same inputs always give the same files

Every date in the data comes from the ingest date, never from the clock, and
the generator is seeded. So re-running a day (an Airflow retry, say) lands
identical bytes. Customer and claim contents also depend on the Faker version,
which `uv.lock` pins.
