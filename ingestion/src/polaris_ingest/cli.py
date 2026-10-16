"""polaris-ingest: generate one day of data and land it in Bronze.

    polaris-ingest run --ingest-date 2026-10-16
    polaris-ingest run --ingest-date 2026-10-17 --day 2

--ingest-date is required on purpose. Airflow passes the run's logical date,
so a retry of Tuesday's run lands Tuesday's data, even if it runs on Wednesday.
"""

from __future__ import annotations

import argparse
from datetime import date

from polaris_ingest.landing.bronze import land_day
from polaris_ingest.landing.sinks import make_sink
from polaris_ingest.sources.synthetic import generate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="polaris-ingest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Generate one day and land it in Bronze")
    run.add_argument("--ingest-date", type=date.fromisoformat, required=True,
                     help="Day being landed, YYYY-MM-DD. Drives every date in the data.")
    run.add_argument("--day", type=int, choices=[1, 2], default=1,
                     help="1 = baseline, 2 = refresh of the previous day's baseline")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--backend", choices=["local"], default="local")
    run.add_argument("--root", default="data/bronze", help="Bronze root folder (local backend)")
    args = parser.parse_args(argv)

    tables = generate(args.ingest_date, day=args.day, seed=args.seed)
    sink = make_sink(args.backend, args.root)
    locations = land_day(sink, tables, args.ingest_date)

    print(f"[polaris-ingest] ingest_date={args.ingest_date} day={args.day} seed={args.seed}")
    for table, rows in tables.items():
        print(f"  {table:<15} {len(rows):>6,} rows  ->  {locations[table]}")
    print(f"  {'_SUCCESS':<15} {'':>6}       ->  {locations['_SUCCESS']}")


if __name__ == "__main__":
    main()
