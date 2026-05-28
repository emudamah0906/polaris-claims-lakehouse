# Polaris — local data directory

This folder holds **generated** datasets used for local dev and CI. The contents
of `data/raw/` and `data/staged/` are gitignored — they are reproducible from
`scripts/generate_polaris_data.py`.

## Regenerate the dataset

```bash
# Day-1 baseline (deterministic, seed=42)
uv run scripts/generate_polaris_data.py --day 1 --seed 42

# Day-2 refresh (simulates a daily load: premium bumps, status changes,
# new claims, payments — drives the SCD2 / incremental dbt demo)
uv run scripts/generate_polaris_data.py --day 2 --seed 42
```

## What gets produced

| File | Rows | Notes |
|------|------|-------|
| `data/raw/customers.csv`       | ~3,000  | PII: SSN, DOB, address, phone |
| `data/raw/policies.csv`        | ~5,000  | AUTO 60% / PROPERTY 40% |
| `data/raw/claims.csv`          | ~10,000 | 5% late-arriving FNOL, 3% fraud-flagged |
| `data/raw/claim_payments.csv`  | ~11,000 | 1–3 payments per closed/paid claim |

## Why generate instead of commit

Keeping the dataset out of git keeps the repo small and lets us tweak the
generator without bloating commit history with binary diffs. Anyone cloning
the repo runs the one command above and gets the identical dataset (seed=42).
