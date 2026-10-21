# polaris-ingest (Stages 2 and 2b)

Lands P&C data in the Bronze layer two ways:

- **Stage 2, file drop:** generate one whole day and land it.
- **Stage 2b, incremental extract:** pull only the rows that changed in the
  Postgres claims system since the last run.

```bash
uv run polaris-ingest run --ingest-date 2026-10-16          # Stage 2, local data/bronze/
uv run pytest ingestion/tests                                # from the repo root
```

| Module | Job |
|---|---|
| `sources/synthetic.py` | Builds the four tables. Dates come from the ingest date, so output is repeatable |
| `sources/postgres.py` | Stage 2b: loads a day into Postgres (upsert, only real changes) and reads a change window |
| `landing/bronze.py` | Stage 2 layout (Hive-style date partitions + per-day `_SUCCESS`) and `land_day()` |
| `landing/incremental.py` | Stage 2b: watermark per table, change windows, `land_extract()` |
| `landing/sinks.py` | Reads and writes bytes. `LocalSink` for a folder, `AdlsSink` for ADLS Gen2 (logs in with `az login`) |
| `cli.py` | The `polaris-ingest` command: `run`, `pg-load`, `extract` |

Row counts and layout: see [`data/README.md`](../data/README.md).

## Stage 2b: incremental extract from Postgres

Postgres 16 runs in the compose stack as `polaris-postgres` (host port 5433).
`infra/docker/postgres/init/01_claims_system.sql` creates the `claims_system`
tables, with an index on each table's change column.

```bash
docker compose -f infra/docker/docker-compose.yml up -d postgres
uv run polaris-ingest pg-load --ingest-date 2026-10-16             # claims app writes day 1
uv run polaris-ingest extract --ingest-date 2026-10-16             # no watermark yet: everything
uv run polaris-ingest pg-load --ingest-date 2026-10-17 --day 2     # claims app writes day 2
uv run polaris-ingest extract --ingest-date 2026-10-17             # only what changed
```

Layout, beside the Stage 2 folders:

```
claims_system/<table>/year=YYYY/month=MM/day=DD/part-00000.csv
_markers/claims_system/ingest_date=YYYY-MM-DD/_SUCCESS
_watermarks/claims_system.json        every run's window, per table
```

### Run on 20 Oct 2026

| Run | customers | policies | claims | claim_payments |
|---|---:|---:|---:|---:|
| pg-load day 1 (inserted) | 3,000 | 5,000 | 10,000 | 11,203 |
| extract 16 Oct (no watermark) | 3,000 | 5,000 | 10,000 | 11,203 |
| pg-load day 2 (inserted / updated) | 0 / 0 | 0 / 385 | 50 / 99 | 100 / 0 |
| extract 17 Oct (changes only) | **0** | **385** | **149** | **100** |
| retry of 17 Oct, after a new change | same files, `shasum -c` 4 × OK | | | |
| extract 18 Oct (one claim reassigned at 09:00) | 0 | 0 | 1 | 0 |

### The rules, and why

- **Window = (last watermark, newest change now].** Strictly greater than the
  watermark: 737 claims sit exactly on 16 Oct's watermark, and `>=` would
  re-pull all of them every day.
- **Watermark saved last,** after the files and the marker. A crash before
  that means the next run re-pulls the same rows (duplicates, which staging
  removes by key) instead of skipping them for good.
- **A retry reuses that day's saved window.** Asking "everything after the
  latest watermark" on a retry would overwrite a good file with an almost empty
  one. Changes that arrive in between go to the next day.
- **Quiet days still write a header-only file,** so "no changes" can be told
  apart from "didn't run".
- **No backfill before a later run.** The windows would overlap.
- **Watermark lives in the sink, not the source.** An extract shouldn't write
  to the database it reads.
- **Payments are insert-only,** so their change column is `created_at`.

### Limits worth knowing

- **Hard deletes are invisible.** A deleted row has no `updated_at` to find.
  Fixes: soft deletes in the source, a periodic full compare, or CDC from the
  database log (Debezium).
- **History can't be replayed.** Postgres only holds the current state, so a
  missed day can't be re-extracted as it was. That's why the extract has to
  run every day (Stage 7 schedules it).
- **Late commits.** A transaction that commits after the extract read the max,
  but with an earlier timestamp, is missed. The usual fix is a small overlap
  (re-read the last few minutes) plus dedupe by key downstream.
