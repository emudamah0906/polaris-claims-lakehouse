"""Incremental extract into Bronze, with a watermark per table (Stage 2b).

Layout, next to the Stage 2 file drop:

    claims_system/<table>/year=YYYY/month=MM/day=DD/part-00000.csv
    _markers/claims_system/ingest_date=YYYY-MM-DD/_SUCCESS
    _watermarks/claims_system.json

The watermark file keeps every run's window, per table:

    {"claims": {"2026-10-16": {"after": null, "up_to": "2026-10-16T00:00:00"},
                "2026-10-17": {"after": "2026-10-16T00:00:00", "up_to": "2026-10-17T00:00:00"}}}

A new day starts where the latest earlier day stopped. A re-run of a day
already done reuses that day's saved window, so a retry pulls the same rows
instead of an empty file.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from datetime import date, datetime

from polaris_ingest.landing.sinks import Sink

SOURCE = "claims_system"
WATERMARK_KEY = f"_watermarks/{SOURCE}.json"


def extract_key(table: str, ingest_date: date) -> str:
    return (
        f"{SOURCE}/{table}/year={ingest_date:%Y}/month={ingest_date:%m}/day={ingest_date:%d}"
        "/part-00000.csv"
    )


def extract_marker_key(ingest_date: date) -> str:
    return f"_markers/{SOURCE}/ingest_date={ingest_date:%Y-%m-%d}/_SUCCESS"


def read_state(sink: Sink) -> dict:
    raw = sink.read(WATERMARK_KEY)
    return json.loads(raw) if raw else {}


def plan_window(
    runs: dict[str, dict], ingest_date: date, current_max: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """(after, up_to) for one table on one day.

    - Day already run: the same window again (a retry).
    - New day: after = where the latest earlier day stopped; up_to = the
      newest change in the table right now.
    - A later day already ran: refuse. Going back would re-read rows the
      later run already took, and the windows would overlap.
    """
    day = ingest_date.isoformat()
    if day in runs:
        w = runs[day]
        return _ts(w["after"]), _ts(w["up_to"])
    if any(d > day for d in runs):
        raise ValueError(
            f"{day} is before a day that already ran ({max(runs)}). Backfills aren't supported."
        )
    earlier = [d for d in runs if d < day]
    after = _ts(runs[max(earlier)]["up_to"]) if earlier else None
    # Nothing new since last time: an empty window that starts and ends at `after`
    if current_max is None or (after is not None and current_max <= after):
        return after, after
    return after, current_max


def rows_to_csv(columns: list[str], rows: list[tuple]) -> bytes:
    """Header always, even with no rows: an empty day still says what its columns are."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def land_extract(
    sink: Sink,
    tables: list[str],
    ingest_date: date,
    current_max: Callable[[str], datetime | None],
    fetch: Callable[[str, datetime | None, datetime | None], tuple[list[str], list[tuple]]],
) -> dict[str, dict]:
    """Extract every table's window into Bronze. Returns {table: {rows, after, up_to}}.

    Order, and why:
      1. Delete the day's old marker.
      2. Write every table's file.
      3. Write the marker. The day is complete.
      4. Save the watermark, LAST. If the run dies before this line, the next
         run starts from the old watermark and pulls the same rows again:
         duplicates, which staging removes by key. Saving it first could skip
         rows forever.
    """
    state = read_state(sink)
    sink.delete(extract_marker_key(ingest_date))
    report = {}
    for table in tables:
        runs = state.setdefault(table, {})
        after, up_to = plan_window(runs, ingest_date, current_max(table))
        if up_to is None:  # empty table, never run: nothing to read
            columns, rows = fetch(table, None, None)
        else:
            columns, rows = fetch(table, after, up_to)
        sink.write(extract_key(table, ingest_date), rows_to_csv(columns, rows))
        runs[ingest_date.isoformat()] = {"after": _iso(after), "up_to": _iso(up_to)}
        report[table] = {"rows": len(rows), "after": after, "up_to": up_to}
    sink.write(extract_marker_key(ingest_date), b"")
    sink.write(WATERMARK_KEY, json.dumps(state, indent=2, sort_keys=True).encode("utf-8"))
    return report


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
