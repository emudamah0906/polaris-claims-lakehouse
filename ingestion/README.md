# polaris-ingest (Stage 2)

Generates one day of synthetic P&C data and lands it in the Bronze layer.

```bash
uv run polaris-ingest run --ingest-date 2026-10-16          # local, data/bronze/
uv run pytest ingestion/tests                                # from the repo root
```

| Module | Job |
|---|---|
| `sources/synthetic.py` | Builds the four tables. Dates come from the ingest date, so output is repeatable |
| `landing/bronze.py` | The layout (Hive-style date partitions + per-day `_SUCCESS`) and `land_day()` |
| `landing/sinks.py` | Writes bytes. `LocalSink` for a folder, `AdlsSink` for ADLS Gen2 (logs in with `az login`) |
| `cli.py` | The `polaris-ingest` command |

Row counts and layout: see [`data/README.md`](../data/README.md).
