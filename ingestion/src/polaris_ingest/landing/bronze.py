"""The Bronze layout, and landing one day into it.

Layout (Hive-style partitions, so Spark and Snowflake can skip whole days):

    <table>/year=YYYY/month=MM/day=DD/part-00000.csv
    _markers/ingest_date=YYYY-MM-DD/_SUCCESS

The _SUCCESS marker is an empty file meaning "this day is complete". There is
one per day, so day 1's marker can never make day 2 look finished. Readers
(later, an Airflow sensor) wait for it before touching that day.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, fields
from datetime import date

from polaris_ingest.landing.sinks import Sink


def partition_key(table: str, ingest_date: date) -> str:
    return (
        f"{table}/year={ingest_date:%Y}/month={ingest_date:%m}/day={ingest_date:%d}"
        "/part-00000.csv"
    )


def marker_key(ingest_date: date) -> str:
    return f"_markers/ingest_date={ingest_date:%Y-%m-%d}/_SUCCESS"


def rows_to_csv(rows: list) -> bytes:
    """Dataclass rows to CSV bytes: header first, columns in field order."""
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([f.name for f in fields(rows[0])])
    for row in rows:
        writer.writerow(asdict(row).values())
    return buf.getvalue().encode("utf-8")


def land_day(sink: Sink, tables: dict[str, list], ingest_date: date) -> dict[str, str]:
    """Write every table for one day, then the marker. Returns {table: location}.

    Safe to re-run for the same day (an Airflow retry): same keys, same bytes,
    files replaced. The order is what makes it safe:
      1. Delete the day's old marker first. If this run dies halfway, readers
         must not see a marker from an earlier run sitting on top of a
         half-replaced day.
      2. Write every table.
      3. Write the marker last. Reaching this line means every table landed.
    """
    sink.delete(marker_key(ingest_date))
    locations = {}
    for table, rows in tables.items():
        locations[table] = sink.write(partition_key(table, ingest_date), rows_to_csv(rows))
    locations["_SUCCESS"] = sink.write(marker_key(ingest_date), b"")
    return locations
