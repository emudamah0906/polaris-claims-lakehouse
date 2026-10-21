"""polaris-ingest: land data in Bronze.

Stage 2, file drop (generate a day and land it):
    polaris-ingest run --ingest-date 2026-10-16
    polaris-ingest run --ingest-date 2026-10-17 --day 2
    polaris-ingest run --ingest-date 2026-10-16 --backend azure --account polarisxxxxxx

Stage 2b, incremental extract from the Postgres claims system:
    polaris-ingest pg-load --ingest-date 2026-10-16            # the claims app writes day 1
    polaris-ingest extract --ingest-date 2026-10-16            # pulls everything (no watermark yet)
    polaris-ingest pg-load --ingest-date 2026-10-17 --day 2    # the app writes day 2's changes
    polaris-ingest extract --ingest-date 2026-10-17            # pulls only what changed

--ingest-date is required on purpose. Airflow passes the run's logical date,
so a retry of Tuesday's run lands Tuesday's data, even if it runs on Wednesday.
"""

from __future__ import annotations

import argparse
import os
from datetime import date

from polaris_ingest.landing.bronze import land_day
from polaris_ingest.landing.sinks import make_sink
from polaris_ingest.sources.synthetic import generate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="polaris-ingest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Generate one day and land it in Bronze")
    _add_day_args(run)
    _add_sink_args(run)

    dsn_help = "Postgres URL. Defaults to $POLARIS_PG_DSN, then the local container"

    pg_load = sub.add_parser("pg-load", help="Write one generated day into the claims system")
    _add_day_args(pg_load)
    pg_load.add_argument("--dsn", help=dsn_help)

    extract = sub.add_parser("extract", help="Pull rows changed since the last watermark")
    extract.add_argument("--ingest-date", type=date.fromisoformat, required=True,
                         help="Day being extracted, YYYY-MM-DD. Names the Bronze folder.")
    extract.add_argument("--dsn", help=dsn_help)
    _add_sink_args(extract)

    vendor = sub.add_parser("vendor-drop", help="Drop the body-shop vendor file + manifest (2c)")
    vendor.add_argument("--ingest-date", type=date.fromisoformat, required=True)
    vendor.add_argument("--seed", type=int, default=42)
    vendor.add_argument("--bad-manifest", action="store_true",
                        help="Claim one row more than sent, to test ADF's row-count check")
    _add_sink_args(vendor)
    # The vendor drops into landing; ADF is what moves it to Bronze
    vendor.set_defaults(root="data/landing", container="landing")

    args = parser.parse_args(argv)
    commands = {"run": _run, "pg-load": _pg_load, "extract": _extract, "vendor-drop": _vendor}
    commands[args.command](args)


def _add_day_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ingest-date", type=date.fromisoformat, required=True,
                   help="Day being landed, YYYY-MM-DD. Drives every date in the data.")
    p.add_argument("--day", type=int, choices=[1, 2], default=1,
                   help="1 = baseline, 2 = refresh of the previous day's baseline")
    p.add_argument("--seed", type=int, default=42)


def _add_sink_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--backend", choices=["local", "azure"], default="local")
    p.add_argument("--root", default="data/bronze", help="Bronze root folder (local backend)")
    p.add_argument("--account", default=os.environ.get("ADLS_ACCOUNT_NAME"),
                   help="Storage account (azure backend). Defaults to $ADLS_ACCOUNT_NAME")
    p.add_argument("--container", default=os.environ.get("ADLS_CONTAINER_BRONZE", "bronze"),
                   help="Container (azure backend). Defaults to $ADLS_CONTAINER_BRONZE or bronze")


def _run(args) -> None:
    # Build the sink before generating, so a missing --account fails in a second
    sink = make_sink(args.backend, args.root, args.account, args.container)
    tables = generate(args.ingest_date, day=args.day, seed=args.seed)
    locations = land_day(sink, tables, args.ingest_date)

    print(f"[polaris-ingest] ingest_date={args.ingest_date} day={args.day} seed={args.seed}")
    for table, rows in tables.items():
        print(f"  {table:<15} {len(rows):>6,} rows  ->  {locations[table]}")
    print(f"  {'_SUCCESS':<15} {'':>6}       ->  {locations['_SUCCESS']}")


def _pg_load(args) -> None:
    from polaris_ingest.sources import postgres

    tables = generate(args.ingest_date, day=args.day, seed=args.seed)
    with postgres.connect(args.dsn) as conn:
        counts = postgres.load(conn, tables)

    print(f"[polaris-ingest pg-load] ingest_date={args.ingest_date} day={args.day}")
    for table, (inserted, updated) in counts.items():
        print(f"  {table:<15} inserted {inserted:>6,}  updated {updated:>6,}")


def _extract(args) -> None:
    from polaris_ingest.landing.incremental import extract_key, land_extract
    from polaris_ingest.sources import postgres

    sink = make_sink(args.backend, args.root, args.account, args.container)
    with postgres.connect(args.dsn) as conn:
        report = land_extract(
            sink,
            list(postgres.TABLES),
            args.ingest_date,
            current_max=lambda t: postgres.max_change(conn, t),
            fetch=lambda t, after, up_to: postgres.fetch_changes(conn, t, after, up_to),
        )

    print(f"[polaris-ingest extract] ingest_date={args.ingest_date} source=claims_system")
    for table, r in report.items():
        print(f"  {table:<15} {r['rows']:>6,} rows  ({r['after']} , {r['up_to']}]"
              f"  ->  {extract_key(table, args.ingest_date)}")


def _vendor(args) -> None:
    from polaris_ingest.sources import vendor

    sink = make_sink(args.backend, args.root, args.account, args.container)
    manifest = vendor.drop(sink, args.ingest_date, args.seed, args.bad_manifest)
    folder = vendor.drop_folder(args.ingest_date)
    print(f"[polaris-ingest vendor-drop] ingest_date={args.ingest_date} container={args.container}")
    print(f"  {folder}/repair_estimates.csv   {manifest['row_count']:,} rows in manifest"
          + ("  (BAD: one more than sent)" if args.bad_manifest else ""))
    print(f"  {folder}/manifest.json         sha256 {manifest['sha256'][:12]}...")


if __name__ == "__main__":
    main()
